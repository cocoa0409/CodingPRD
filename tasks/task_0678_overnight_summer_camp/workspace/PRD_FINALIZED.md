# Overnight Summer Camp API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Overnight Summer Camp API, the operational backbone of a sleepaway camp that must reconcile bed capacity, staffing safety ratios, medical clearance, and tuition accounting in a single coherent system. A camp season runs as a tree of sessions, each session subdividing into gender- and age-banded cabins and a calendar of activity offerings, while applications, health forms, financial aid, payments, and canteen accounts cut across that tree to follow an individual camper from first inquiry through enrollment and departure.

The central tension the API mediates is between *demand* and *safety*: guardians want their children enrolled, but a session may only run children when its cabins are adequately staffed, when each camper's medical paperwork has been reviewed by the infirmary, and when seats are genuinely available against a hard capacity. An application therefore advances along two independent axes at once — an enrollment axis tracking the camper's progress from draft to confirmed bed, and a payment axis tracking deposit, balance, and refund obligations — and the system continuously derives session-level staffing posture and forward-looking and authoritative tuition balances from the underlying ledger of payments and aid.

Four kinds of actor share the system. A camp director configures the camp and its sessions, builds cabins and staffing, runs intake checkpoints, and adjudicates aid. Guardians manage their own campers, applications, health submissions, payments, elective bookings, and canteen spending. Infirmary nurses review health forms — clearing or flagging them — without touching enrollment or money. And an anonymous caller may do exactly one thing: register a guardian account. The remainder of this document defines the global contracts that bind every endpoint, the business rules that govern each workflow, the full endpoint surface, and the complete error catalogue.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request other than guardian registration and clock administration must be authenticated with two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which they act. A request missing or malformed in either header — on any endpoint that requires authentication — is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly four roles, spelled precisely as `Anonymous`, `Guardian`, `CampDirector`, and `InfirmaryNurse`. When a well-authenticated caller invokes an operation their role is not permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The four roles bind to identity differently. When `X-User-Role` is `Guardian`, `X-User-ID` is the `id` of the acting `Guardian`; ownership checks on any resource that references a `Guardian` compare the resource's owning-guardian foreign key to `X-User-ID`. Concretely, every `Camper` carries the `guardian_user_id` of its owner, and applications, health forms, payments, activity enrollments, and canteen accounts all chain back to a camper. A `Guardian` may act only within their own ownership chain; an attempt to act on a camper, application, health form, or payment they do not own is rejected with `ERR_NOT_RESOURCE_OWNER`.

When `X-User-Role` is `CampDirector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. When `X-User-Role` is `InfirmaryNurse`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; nurses are scoped by role rather than by ownership and may clear or flag any submitted health form. When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque, unauthenticated identifier not tied to any persisted entity; the anonymous role exists solely so that a prospective guardian can self-register. Setting the logical clock is reserved to the `CampDirector` role and is not available to `Anonymous`.

### 2.2. API Response Structure

#### Standard Success Response Format

All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z",
    "limit": 10,
    "offset": 0,
    "total_count": 100,
    "has_more": true
  },
  "response_type": "object" | "array",
  "data": { }
}
```

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

#### Standard Error Response Format

All error API responses (4xx status codes) follow this standard envelope format:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "A human-readable explanation of the error."
  }
}
```

- The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
- The `error_id` is a unique, machine-readable string that identifies the specific error.
- The `message` provides a human-readable explanation of what went wrong.

---

### 2.3. Pagination

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

All primary resources carry a standard set of system-managed fields. Each has an `id` formatted as a UUID with no type prefix, and a `created_at` timestamp expressed as an ISO 8601 UTC instant with three fractional digits indicating when the resource was first created. Most resources additionally carry an `updated_at` timestamp — likewise ISO 8601 UTC with three fractional digits, refreshed on every mutation — and a `version`, an integer that begins at its initial value on creation and increments by one on every modification. The single exception is the `CanteenTransaction`, which is an append-only event record: it carries only `id` and `created_at`, and has neither `updated_at` nor `version` because it is never mutated after creation.

The system operates against a **logical clock** rather than wall-clock time. At server startup the clock reads exactly `2026-04-01T00:00:00Z`, and before any clock-setting call it remains pinned to that default and never falls back to the real-world time. A director-only test-driving capability advances the clock to a supplied `to_iso8601` instant and returns the new value as `now`. All temporal comparisons in this specification — offer expiry, session start and end gates, tuition tiering — read this logical clock.

### 2.5. Hierarchical Consistency and Derived-Field Reconciliation

Many fields in this system are *computed*: they are never written directly by a client but are reconciled by the server whenever an underlying event changes them. A session's `enrolled_count`, `committed_count`, `waitlist_length`, and `ratio_posture`; a cabin's `occupied_bunks`, `staff_weight_x10`, and `is_staffable`; a camper's `health_status`; an application's `list_tuition_cents`, `aid_cents`, `estimated_balance_cents`, `settled_balance_cents`, and `deposit_paid_cents`; an offering's `seats_taken`; and a canteen account's `balance_cents` and `is_low` are all derived. Whenever a write changes one of these, the owning resource is mutated: its `updated_at` is refreshed and its `version` increments. A reconciliation that cascades upward (for example, an enrollment that changes a cabin's occupancy and in turn the session's posture) independently mutates each affected resource the same way.

State propagates both downward and upward through the session tree. A session's posture is derived from the staffing and occupancy of its cabins; a camper's `health_status` mirrors that camper's latest health-form status. Because these mirrors are server-maintained, the server may transition or recompute a parent or child without an explicit client request on that specific resource — the run-intake cascade and the staffing recomputation that follows a cabin assignment are the principal examples.

### 2.6. Nested Resource Retrieval

When an endpoint path contains multiple resource identifiers — for example a cabin nested under a session, or an activity offering nested under a session — the system validates the existence of each identifier in left-to-right path order. The request is rejected with `ERR_NOT_FOUND` corresponding to the first identifier in the path that does not resolve to an existing resource, before any deeper resource or body-referenced resource is consulted. This ordering also governs creation and modification: a child cannot be created under a parent that does not exist, and the parent's resolution always precedes the child's.

### 2.7. Monetary Values and Precision

All monetary quantities in this system — tuition, deposits, aid, payments, and canteen balances — are represented and stored as **integer cents**. Because every monetary input is already an integer count of cents, all monetary calculations are performed in integer arithmetic with no rounding and no fractional component at any step. Staffing weight is similarly kept in integers by scaling: a cabin's effective staff weight is stored as `staff_weight_x10`, ten times the true weight, so that a counselor-in-training counted as half a counselor still lands on a whole integer.

### 2.8. Optimistic Concurrency Control

Several writes that supersede a shared parent require the client to declare the parent version it last observed, so that a write computed against a stale snapshot is refused rather than silently overwriting another writer's change. Two such supersede points exist.

First, assigning a camper to a bunk targets a cabin and must carry `expected_cabin_version` matching that cabin's current `version`. If another assignment has consumed a bunk and advanced the cabin's `version` since the client read it, the client's view of the remaining bunk capacity is out of date; the request is therefore rejected with `ERR_STALE_VERSION` and HTTP 412, preventing it from assigning a bunk it has not observed to be free.

Second, approving a financial-aid award reads the target application's current aid total to enforce the tuition ceiling, so the approval must carry `expected_application_version` matching that application's current `version`. If another award was approved in the interim, the application's `version` has advanced and the approver's snapshot of remaining tuition headroom is stale; the approval is rejected with `ERR_STALE_VERSION` and HTTP 412.

Beyond these create-with-supersede writes, the four director-driven session transitions — open-enrollment, start, close — each require `expected_session_version` matching the target session's current `version`, and updating camp configuration requires `expected_camp_version` matching the camp's current `version`. In every case a mismatch yields `ERR_STALE_VERSION` (HTTP 412). Endpoints not enumerated here take no version field.

### 2.9. Staffing Ratio and Session Posture

Camper safety is gated on staffing. Each camp declares a `counselor_camper_ratio` — the maximum number of campers a single qualified counselor-equivalent may cover, defaulting to 6 — and a `cit_counts_as_half` flag, defaulting to true, governing how much a counselor-in-training contributes to coverage. These two settings, together with the per-cabin occupancy and assigned staff, drive a derived **ratio posture** on each session that gates whether children may be confirmed into beds. The precise weighting, the staffable threshold, and the posture aggregation are defined in §3 alongside the workflows that consume them.

### 2.10. Health, Infirmary, and Waterfront Safety

The infirmary is the system's medical gate. Every camper carries a `health_status` enumerated as `NONE`, `PENDING`, `CLEARED`, or `FLAGGED`, mirroring the camper's latest health form. A camper begins at `NONE`; submitting a health form moves the camper to `PENDING`; a nurse's review moves it to `CLEARED` or `FLAGGED`. Two safety gates depend on this: an application may not be confirmed into a bed until its camper is `CLEARED`, and an activity offering flagged as requiring a swim test may only be booked for a camper who is `CLEARED`. A further infirmary rule guards anaphylaxis: a health form declaring a life-threatening allergy must have an EpiPen on file before it can be submitted or cleared. These gates and their error codes are detailed in §3.

## 3. Business Logic & Workflows

### 3.1. Camp Configuration and the Season Foundation

A `CampDirector` lays the foundation by creating a `Camp`, the configuration root. A camp is created with a `name` and a set of optional configuration knobs that fall back to defaults when omitted: `counselor_camper_ratio` (default 6), `cit_counts_as_half` (default true), `deposit_cents` (default 25000, the non-refundable deposit that converts an offered application to a paid one), `deposit_grace_days` (default 7, the number of days an offered application may sit before intake expires it back to the waitlist), and `canteen_low_balance_cents` (default 1000, the balance at or below which a canteen account is marked low). The director may later adjust any of these knobs. Updating camp configuration requires `expected_camp_version`; when the `cit_counts_as_half` flag changes, every cabin's effective staff weight and staffable flag are recomputed across the whole camp, and the camp's `version` increments.

Under a camp, the director creates `Session` resources. A session is created with a `name`, a start instant `starts_on`, an end instant `ends_on` that must fall strictly after `starts_on`, a visiting-day instant `visiting_day_on` that must fall within the inclusive window from `starts_on` to `ends_on`, and a total bed `capacity` across all of the session's cabins. A start instant not strictly before the end, or a visiting day outside the session window, is rejected — the former as `ERR_INVALID_REQUEST` and the latter as `ERR_VISITING_DAY_OUT_OF_RANGE`. A newly created session begins in `PLANNING` status with `enrollment_open` true, its derived counts at zero, and `ratio_posture` at `UNDERSTAFFED`. Each session records the `camp_id` of its parent. Sessions may be listed under their camp and filtered by `camp_id` or `status`, and a single session may be fetched to read its live counts and posture.

A session walks a lifecycle of `PLANNING`, then `ENROLLING`, then `RUNNING`, then `CLOSED`, with `CLOSED` terminal. Opening enrollment moves a session from `PLANNING` to `ENROLLING`; it requires that the session already have at least one cabin (otherwise `ERR_NO_CABINS`) and that `expected_session_version` match, and it sets `enrollment_open` to true and increments the session's `version`. Starting a session moves it from `ENROLLING` to `RUNNING`: it requires that the logical clock have reached or passed `starts_on` (otherwise `ERR_SESSION_NOT_STARTED`), that the session's `ratio_posture` be exactly `STAFFED` (otherwise `ERR_SESSION_UNDERSTAFFED`), and that `expected_session_version` match. Starting sets `enrollment_open` to false, transitions every `WAITLISTED` application for the session to `WITHDRAWN` (a withdrawal sets `payment_status` to `REFUND_DUE` only when the application has a positive `deposit_paid_cents`, which a waitlisted application never does), and increments the session's `version`. Closing a session moves it from `RUNNING` to `CLOSED`: it requires the clock to have reached or passed `ends_on` (otherwise `ERR_SESSION_NOT_ENDED`) and `expected_session_version` to match. Closing leaves all `ENROLLED` applications enrolled as a historical record, generates no refunds, and increments the session's `version`.

### 3.2. Cabins, Staffing, and the Ratio Posture

Within a session the director builds `Cabin` resources, the physical beds. A cabin is created with a `name`, a `gender_band` of `BOYS`, `GIRLS`, or `ALL`, a lowest accepted camper age `min_age` (inclusive), a highest accepted camper age `max_age` (inclusive) that must be at least `min_age`, and a `bunk_capacity` counting the cabin's bunks. A cabin where `max_age` is below `min_age` is rejected with `ERR_INVALID_REQUEST`. Each cabin records the `session_id` of its parent and begins with `occupied_bunks` at zero, `staff_weight_x10` at zero, and — because an empty cabin is treated as adequately staffed — `is_staffable` true. A cabin's `occupied_bunks` counts the applications bunked there whose enrollment is in either `DEPOSIT_PAID` or `ENROLLED` status. Cabins may be listed under a session, filtered by `session_id`, and fetched individually to read occupancy and staffing.

Staff are modeled separately. A `StaffMember` is created under a camp with a `full_name`, a `role_kind` of `COUNSELOR` or `CIT` (counselor-in-training), and an optional `is_background_cleared` flag defaulting to false. Each staff member records the `camp_id` of its parent. Staff are joined to cabins through a `CabinAssignment`, a flat junction created with a `cabin_id` and a `staff_member_id`; an assignment begins `ACTIVE` and may later move to `RELEASED`, with `ACTIVE` and `RELEASED` its only states. Assigning a staff member whose `is_background_cleared` is false is refused with `ERR_STAFF_NOT_CLEARED` — only background-cleared staff may be placed in a cabin. Creating a cabin assignment recomputes the target cabin's `staff_weight_x10` and `is_staffable`, then recomputes the session's `ratio_posture`. Releasing an assignment moves it from `ACTIVE` to `RELEASED` and likewise recomputes the cabin's `staff_weight_x10`, the cabin's `is_staffable`, and the session's `ratio_posture`; however, a release is refused with `ERR_CABIN_UNDERSTAFFED` if it would leave any cabin that holds enrolled campers no longer staffable.

A cabin's **effective staff weight** is computed in tenths to stay integral. Summing only over `ACTIVE` cabin assignments to this cabin whose staff member is background-cleared, a `COUNSELOR` contributes 10, and a `CIT` contributes 5 when the camp's `cit_counts_as_half` flag is true or 10 when that flag is false. The sum is the cabin's `staff_weight_x10`. Assignments that are released, or whose staff member is not background-cleared, contribute nothing.

A cabin's `is_staffable` flag then compares that weight against the campers present. The required weight in tenths is the number of occupied bunks divided by the camp's `counselor_camper_ratio`, rounded up to the next whole number of counselor-equivalents, multiplied by 10. A cabin with no occupied bunks is always staffable; otherwise the cabin is staffable exactly when its `staff_weight_x10` is greater than or equal to that required weight. The boundary is inclusive: a cabin whose weight exactly equals the requirement is staffable.

The session's `ratio_posture` aggregates over only those cabins that currently hold campers — those with `occupied_bunks` greater than zero. If no cabin in the session holds any camper, the posture is `UNDERSTAFFED`, since an empty session cannot be started. Otherwise, if every camper-holding cabin is staffable, the posture is `STAFFED`; if at least one camper-holding cabin is staffable but not all are, the posture is `MARGINAL`; and if no camper-holding cabin is staffable, the posture is `UNDERSTAFFED`. This posture is the gate the session-start transition consults, and it is recomputed whenever a child cabin's `is_staffable`, `occupied_bunks`, or `staff_weight_x10` changes, or when an application enrolls or withdraws.

### 3.3. Campers, Guardians, and the Health-Form Loop

A prospective family begins anonymously: the registration endpoint creates a `Guardian` from an `email` (the unique login email across guardians), a `full_name`, and a `phone`. Once registered and acting as `Guardian`, the parent creates `Camper` resources, each with a `full_name`, an `age` in years at registration, and a `gender` of `BOY` or `GIRL`. A camper's `guardian_user_id` is set to the acting `X-User-ID`, and its `health_status` starts at `NONE`. Campers may be listed (filtered by `guardian_user_id`) and fetched individually.

Before a camper can be put forward for a session, the infirmary process must begin. A guardian creates a `HealthForm` for one of their campers, supplying the `camper_id` and three optional medical declarations: `has_life_threatening_allergy` (default false), `epipen_on_file` (default false), and `daily_medication_count` (default 0, the number of daily scheduled medications the infirmary would administer). A new health form starts in `DRAFT`. The form also carries a `review_note`, defaulting to an empty string, where a nurse records remarks on review.

A health form walks `DRAFT`, then `SUBMITTED`, then either `CLEARED` or `FLAGGED`, with a revision loop from `FLAGGED` back to `SUBMITTED`; `CLEARED` is terminal. When a guardian submits a form — moving it from `DRAFT` to `SUBMITTED`, or resubmitting it from `FLAGGED` back to `SUBMITTED` — the system enforces the anaphylaxis gate: if `has_life_threatening_allergy` is true, then `epipen_on_file` must also be true, or the submit is refused with `ERR_EPIPEN_REQUIRED`. A successful submit sets the camper's `health_status` to `PENDING`. An `InfirmaryNurse` then reviews a `SUBMITTED` form. Clearing it moves the form to `CLEARED`, sets the camper's `health_status` to `CLEARED`, and re-applies the same anaphylaxis gate (a form declaring a life-threatening allergy without an EpiPen on file cannot be cleared, again `ERR_EPIPEN_REQUIRED`); an optional `review_note` may accompany the clearance. Flagging instead moves the form to `FLAGGED`, sets the camper's `health_status` to `FLAGGED`, records the `review_note`, and carries no preconditions. A flagged form is corrected and resubmitted by the guardian, re-entering `SUBMITTED` and returning the camper to `PENDING` for re-review. Health forms may be listed (filtered by `camper_id` or `status`) and fetched individually.

### 3.4. Application Intake: Submission, Offers, and the Waitlist

An `Application` ties a camper to a session and is the workhorse of the system. A guardian creates a draft application with a `camper_id` and a `session_id`; it begins with `enroll_status` of `DRAFT` and `payment_status` of `UNBILLED`. The application also carries a system-maintained `cabin_id` recording which cabin the camper is bunked in once a bunk is assigned (null before assignment), a `submitted_at` timestamp set when the application is submitted (the waitlist ordering key, earliest first), and an `offer_expires_at` instant marking when an offer lapses. Applications may be listed and filtered by `camper_id`, `session_id`, `cabin_id`, or `enroll_status`, and fetched individually to read their live balances and statuses.

The enrollment axis advances through `DRAFT`, `SUBMITTED`, then either `WAITLISTED` or `OFFERED`, then `DEPOSIT_PAID`, then `ENROLLED`, with `WITHDRAWN` as the terminal escape state. When a guardian submits a draft application, three preconditions are checked: the session must be in `ENROLLING` status with `enrollment_open` true (otherwise `ERR_ENROLLMENT_CLOSED`); the camper's `health_status` must be either `PENDING` or `CLEARED`, meaning a health form has at least been submitted (otherwise `ERR_HEALTH_FORM_MISSING`); and the session must contain at least one cabin whose `gender_band` admits the camper's gender and whose inclusive age band from `min_age` to `max_age` contains the camper's age (otherwise `ERR_NO_ELIGIBLE_CABIN`). On submit the system sets `submitted_at` to the current clock, snapshots `list_tuition_cents` (see §3.5), and immediately routes the application: `SUBMITTED` is transient. If the session's `committed_count` is below `capacity`, a seat is available and the application is auto-routed to `OFFERED`; otherwise it is auto-routed to `WAITLISTED`.

The `committed_count` is the number of applications for the session whose enrollment is `OFFERED`, `DEPOSIT_PAID`, or `ENROLLED` — that is, all applications currently holding a seat against capacity. The `waitlist_length` counts applications in `WAITLISTED`, and `enrolled_count` counts those in `ENROLLED`. When a submitted application is routed to `OFFERED`, the system sets `offer_expires_at` to the current clock plus the camp's `deposit_grace_days`, and the payment axis moves to `DEPOSIT_DUE` with the estimated balance recomputed. When instead routed to `WAITLISTED` because `committed_count` is at or above `capacity`, the waitlist length is recomputed and the payment axis stays `UNBILLED`.

The director periodically runs an **intake checkpoint** on a session, a two-phase cascade. First, every `OFFERED` application whose `offer_expires_at` is strictly before the current clock is recycled back to `WAITLISTED` — its payment axis reverts to `UNBILLED`, its `offer_expires_at` is cleared, and `committed_count` is decremented, freeing a seat. Second, while `committed_count` remains below `capacity`, the system promotes the earliest-submitted waitlisted application — ordered by `submitted_at` ascending, breaking ties by earliest `created_at` — from `WAITLISTED` to `OFFERED`, setting its `offer_expires_at` to the current clock plus `deposit_grace_days`, moving its payment axis to `DEPOSIT_DUE`, and recomputing `waitlist_length` and `committed_count`. Because expiry frees seats before promotion runs, a single intake pass can both expire a lapsed offer and promote the next applicant into the seat it released.

### 3.5. Tuition Pricing and the Two Balances

When an application is submitted, the system snapshots its gross session tuition into `list_tuition_cents` using a tiered, surcharge-adjusted calculation whose evaluation order is fixed and does not commute. First, the system determines how many whole days before the session start the application is being submitted: the number of days is the difference between the session's `starts_on` and the current clock, divided into whole days and rounded down (this figure may be negative if submission occurs after the session has begun). Second, the early-bird tier is selected from that figure against a base tuition of 400000 cents: if the application is submitted at least 60 days before the start, the tier amount is the base tuition reduced by an early discount of 30000 cents; if it is submitted at least 14 days before the start but fewer than 60, the tier amount is exactly the base tuition; and otherwise — fewer than 14 days before, including any negative figure — the tier amount is the base tuition increased by a late surcharge of 25000 cents. Third, and only after the tier is fixed, a medical-support surcharge is added: the system reads the camper's latest health form (by creation time) whose status is `SUBMITTED`, `CLEARED`, or `FLAGGED`, and adds 1500 cents for each daily scheduled medication on that form plus, if that form declares a life-threatening allergy, a further 5000 cents of EpiPen support. The final `list_tuition_cents` is the chosen tier amount plus this medical-support surcharge. All quantities are integer cents, so no rounding occurs.

Two balances are then derived from the same underlying ledger of aid and payments, and they deliberately differ. The **estimated balance** (`estimated_balance_cents`) is the forward-looking, optimistic figure shown to the guardian. It optimistically assumes every still-pending aid request will ultimately be approved: its aid set therefore includes awards in either `REQUESTED` or `APPROVED` status (excluding denied and revoked awards), pooled into a single sum. It pools all applied payments — payments in `APPLIED` status — into a second sum. The estimated balance is the list tuition minus the optimistic aid total minus the applied-payment total, floored at zero in a single step so it can never go negative.

The **settled balance** (`settled_balance_cents`) is the authoritative, chronological figure used to compute refunds and to decide when an application is paid in full. Its aid set is narrower: it counts only awards in `APPROVED` status — a still-requested award contributes nothing until it is actually approved. The settled balance replays events against a running total that starts at the list tuition. The events are the approved aid awards (each reducing the running total by its `amount_cents`) and the applied payments (each reducing the running total by its `amount_cents`), sorted by `created_at` ascending; when two events share the same `created_at`, the aid event is applied before the payment event. Each event reduces the running total but floors it at zero per event before the next is applied, and the final running total is the settled balance. Because the estimated balance counts pending requests and the settled balance does not, the two diverge precisely when an application has a requested-but-unapproved award.

A separate `deposit_paid_cents` field records the deposit credited toward tuition once the deposit is paid, and `aid_cents` records the total approved aid currently applied to the application; both are recomputed whenever aid or payments change.

### 3.6. Deposits, Enrollment, and Withdrawal

A guardian converts an offer into a held bed by paying the deposit. Paying a deposit on an `OFFERED` application moves it to `DEPOSIT_PAID`; it requires that the current clock be at or before `offer_expires_at` (otherwise `ERR_OFFER_EXPIRED`) and that the submitted `amount_cents` exactly equal the camp's `deposit_cents` (otherwise `ERR_DEPOSIT_AMOUNT_MISMATCH`). A successful deposit creates a `Payment` of kind `DEPOSIT` in `APPLIED` status, sets `deposit_paid_cents` to the camp's deposit amount, moves the payment axis to `DEPOSIT_SETTLED`, and recomputes both balances. Note that a camper's bunk occupancy counts an application from `DEPOSIT_PAID` onward, so the cabin's `occupied_bunks` reflects deposit-paid as well as enrolled campers.

Before a camper can be confirmed, the director assigns a bunk. Assigning a bunk targets a cabin and carries the `application_id` of a deposit-paid (or offered-with-deposit) application together with `expected_cabin_version`. The cabin must belong to the same session as the application (otherwise `ERR_REFERENTIAL_MISMATCH`); the cabin's `gender_band` must admit the camper's gender (otherwise `ERR_CABIN_GENDER_MISMATCH`); the cabin's inclusive age band must contain the camper's age (otherwise `ERR_CABIN_AGE_MISMATCH`); and the assignment must not push `occupied_bunks` beyond `bunk_capacity` (otherwise `ERR_CABIN_FULL`). On success the application's `cabin_id` is set, the cabin's `occupied_bunks` is incremented, the cabin's `is_staffable` is recomputed, the session's `ratio_posture` is recomputed, and the cabin's `version` increments.

The director then enrolls a `DEPOSIT_PAID` application, moving it to `ENROLLED`. Four preconditions guard this transition: the camper's `health_status` must be exactly `CLEARED` (otherwise `ERR_HEALTH_NOT_CLEARED`); the application's `cabin_id` must be set, meaning a bunk has been assigned (otherwise `ERR_NO_BUNK_ASSIGNED`); the target cabin must be `is_staffable` true after counting this camper (otherwise `ERR_CABIN_UNDERSTAFFED`); and the session's `ratio_posture` must not be `UNDERSTAFFED` (otherwise `ERR_SESSION_UNDERSTAFFED`). On success the enrollment moves to `ENROLLED`, the session's `enrolled_count` is incremented, and the cabin's `occupied_bunks` is left unchanged because the camper was already counted at deposit time. The payment axis moves to `BALANCE_DUE` if the estimated balance is greater than zero, or to `PAID_IN_FULL` if it is not, and the session's `ratio_posture` is recomputed.

A guardian may withdraw an application, and the cascade depends on where it sits. Withdrawing an `OFFERED` application simply decrements `committed_count`, freeing a seat. Withdrawing a `DEPOSIT_PAID` application reverses every `APPLIED` payment on the application to `REVERSED` and moves the payment axis to `REFUND_DUE`; if a `cabin_id` is set, the cabin's `occupied_bunks` is decremented, its `is_staffable` recomputed, and the `cabin_id` cleared; `committed_count` is decremented; and every `BOOKED` activity enrollment for the application is moved to `DROPPED`, each freeing a seat on its offering. Withdrawing an `ENROLLED` application is permitted only when the session is not `RUNNING` (otherwise `ERR_SESSION_RUNNING_NO_WITHDRAW`); it reverses all `APPLIED` payments to `REVERSED`, moves the payment axis to `REFUND_DUE`, decrements both `enrolled_count` and `committed_count`, decrements the cabin's `occupied_bunks`, recomputes the cabin's `is_staffable` and clears the `cabin_id`, drops all `BOOKED` activity enrollments (each freeing a seat), and recomputes the session's `ratio_posture`. A withdrawn application is terminal.

The guardian settles the remaining tuition by paying a balance on a `BALANCE_DUE` application, supplying an `amount_cents`. This creates a `Payment` of kind `BALANCE` in `APPLIED` status, recomputes both balances, and moves the payment axis to `PAID_IN_FULL` once the settled balance reaches zero. A `Payment` carries the `application_id` it belongs to, a `kind` of `DEPOSIT` or `BALANCE`, an `amount_cents`, and a `status` of `APPLIED` or `REVERSED`. Payments may be listed (filtered by `application_id` or `status`) and fetched individually.

### 3.7. Financial Aid Adjudication

A guardian requests financial aid against one of their applications by creating a `FinancialAidAward` with the `application_id`, a `kind` of `NEED_GRANT` or `MERIT_SCHOLARSHIP`, and a requested `amount_cents`. The award begins `REQUESTED` and may then be approved or denied; an approved award may later be revoked. Its states are `REQUESTED`, `APPROVED`, `DENIED`, and `REVOKED`, with `DENIED` and `REVOKED` terminal. The referenced application must resolve, or the request is rejected with `ERR_REFERENTIAL_MISMATCH`. Awards may be listed (filtered by `application_id` or `status`) and fetched individually.

A `CampDirector` adjudicates. Approving a requested award moves it to `APPROVED`; it requires that the application not be `WITHDRAWN` (otherwise `ERR_INVALID_STATE`), that the requested `amount_cents` plus the aid already approved on the application not exceed the application's `list_tuition_cents` (otherwise `ERR_AID_EXCEEDS_TUITION`), and — as the optimistic-concurrency guard described in §2.8 — that `expected_application_version` match the application's current `version`. On approval the application's `aid_cents` is recomputed and both balances are recomputed, and the application's `version` increments. Denying a requested award simply moves it to `DENIED` with no preconditions and no side effects. Revoking an approved award moves it to `REVOKED`; it is permitted only when the application's payment axis is not `PAID_IN_FULL` (otherwise `ERR_INVALID_STATE`). Because that precondition forbids revoking a `PAID_IN_FULL` application, revocation never alters the payment axis: it removes the award from the aid total and recomputes `aid_cents` and both balances, leaving `payment_status` unchanged.

### 3.8. Electives: Offerings, Booking, and Scheduling Conflicts

The director populates a session's calendar with `ActivityOffering` resources, the electives. An offering is created under a session with a `name`, a `slot_day` (a 1-based day index within the session), a `starts_minute` (the start expressed as a minute-of-day from 0 up to but not including 1440), an `ends_minute` (a minute-of-day that must be strictly greater than `starts_minute`, otherwise `ERR_INVALID_REQUEST`), a `seat_capacity` counting the camper seats, an optional `setup_buffer_minutes` (default 0, the changeover minutes after the offering ends during which a camper may not begin another offering), and an optional `requires_swim_test` flag (default false, the waterfront safety gate). Each offering records its parent `session_id` and tracks `seats_taken`, the count of its activity enrollments in `BOOKED` status. Offerings may be listed under a session (filtered by `session_id` or `slot_day`) and fetched individually.

A guardian books a camper into an elective by creating an `ActivityEnrollment` with the `offering_id` and the `application_id`. The enrollment begins `BOOKED` and may later be `DROPPED`, its only two states. The referenced offering and application must resolve and be in scope (otherwise `ERR_REFERENTIAL_MISMATCH`). If the offering's `requires_swim_test` flag is true, the camper's `health_status` must be `CLEARED`, the waterfront gate (otherwise `ERR_SWIM_TEST_REQUIRED`). The booking must not push `seats_taken` beyond `seat_capacity` (otherwise `ERR_ACTIVITY_FULL`). On success the enrollment is `BOOKED` and the offering's `seats_taken` is incremented. Dropping a booking moves it from `BOOKED` to `DROPPED` and decrements the offering's `seats_taken`. Activity enrollments may be listed (filtered by `offering_id`, `application_id`, or `status`) and fetched individually.

Booking also enforces two time-conflict checks, both evaluated against the application's existing `BOOKED` enrollments on the same `slot_day` as the new offering, and both rejecting with `ERR_ACTIVITY_TIME_CONFLICT`. The first is a raw-interval collision: treating each offering's interval as half-open from its `starts_minute` up to but not including its `ends_minute`, a conflict exists if the new offering's interval and an existing booking's interval overlap. Because the intervals are half-open, exact adjacency — where one offering's `ends_minute` equals the other's `starts_minute` — is allowed and is not a conflict. The second is a buffer collision that applies even when the raw intervals are disjoint: the new offering's `starts_minute` must be at least the existing booking's `ends_minute` plus that existing offering's `setup_buffer_minutes`, and symmetrically the existing booking's `starts_minute` must be at least the new offering's `ends_minute` plus the new offering's `setup_buffer_minutes`. The buffer boundary is inclusive: a start exactly at the other's end plus buffer is allowed. A booking is rejected if either the raw intervals overlap or the buffer window is violated on that slot day.

### 3.9. The Canteen Store Account

Each enrolled application may have a `CanteenAccount`, the camper's store wallet, opened with the application's `application_id` — one account per application. A new account starts with `balance_cents` at zero and `is_low` true. The account's balance is derived: it is the sum of the `amount_cents` of all `APPLIED` canteen transactions of kind `DEPOSIT` minus the sum of the `amount_cents` of all `APPLIED` canteen transactions of kind `PURCHASE`. The account's `is_low` flag is true exactly when `balance_cents` is at or below the camp's `canteen_low_balance_cents`. Canteen accounts may be listed (filtered by `application_id`) and fetched individually to read the live balance.

A `CanteenTransaction` is an append-only event recording a `account_id`, a `kind` of `DEPOSIT` (a credit) or `PURCHASE` (a debit), and a positive `amount_cents`. A deposit credits the account and a purchase debits it; on recording, the transaction is `APPLIED` and the owning account's `balance_cents` and `is_low` are recomputed. Overdrafts are forbidden: a purchase whose `amount_cents` exceeds the account's current `balance_cents` is rejected with `ERR_CANTEEN_INSUFFICIENT_FUNDS`. A purchase whose amount exactly equals the current balance is allowed. The referenced account must resolve and be in scope (otherwise `ERR_REFERENTIAL_MISMATCH`). Transactions for an account may be listed.

### 3.10. Validation Order Across Every Write

Because many of the rules above can fail simultaneously on a single request, the system evaluates its validations in a fixed precedence so that the same input always surfaces the same error. The order, from first to last, is: authentication of the headers (`ERR_UNAUTHENTICATED`); whether the acting role is permitted for the endpoint (`ERR_FORBIDDEN_ROLE`); guardian ownership of the targeted camper, application, health form, or payment (`ERR_NOT_RESOURCE_OWNER`); existence of every path- and body-referenced resource, validated left-to-right along the path (`ERR_NOT_FOUND`); referential scope of body foreign keys, such as a bunk-assignment cabin belonging to the application's session or an aid award resolving to its application (`ERR_REFERENTIAL_MISMATCH`); whether the target resource is in a valid state for the requested transition (`ERR_INVALID_STATE`); the health and infirmary safety gates — EpiPen-required on submit and clear, cleared-required before enroll, swim-test-cleared for waterfront offerings (`ERR_EPIPEN_REQUIRED`, `ERR_HEALTH_NOT_CLEARED`, `ERR_SWIM_TEST_REQUIRED`); the eligibility and matching constraints — cabin gender and age band fit at submit, gender and age fit at bunk assignment, staffing ratio, and staff background clearance (`ERR_NO_ELIGIBLE_CABIN`, `ERR_CABIN_GENDER_MISMATCH`, `ERR_CABIN_AGE_MISMATCH`, `ERR_CABIN_UNDERSTAFFED`, `ERR_STAFF_NOT_CLEARED`); the date-window and scheduling-temporal constraints — session start not before `starts_on`, close not before `ends_on`, visiting day within window, and activity time and buffer conflicts (`ERR_SESSION_NOT_STARTED`, `ERR_SESSION_NOT_ENDED`, `ERR_VISITING_DAY_OUT_OF_RANGE`, `ERR_ACTIVITY_TIME_CONFLICT`); the capacity and quota constraints — session committed count below capacity for an offer, cabin bunk capacity, and activity seat capacity (`ERR_SESSION_FULL`, `ERR_CABIN_FULL`, `ERR_ACTIVITY_FULL`); the fiscal constraints — deposit amount matching, aid not exceeding tuition, and canteen no-overdraft (`ERR_DEPOSIT_AMOUNT_MISMATCH`, `ERR_AID_EXCEEDS_TUITION`, `ERR_CANTEEN_INSUFFICIENT_FUNDS`); the offer-not-expired check on deposit payment (`ERR_OFFER_EXPIRED`); the optimistic-concurrency version check on supersede writes (`ERR_STALE_VERSION`); and finally the basic request-shape checks — required fields present and well-typed, valid enum members, positive amounts where required, end after start, max age at least min age, and end minute after start minute (`ERR_INVALID_REQUEST`). The two enrollment-specific conflicts — `ERR_ENROLLMENT_CLOSED` when a session is not open for submission and `ERR_NO_CABINS` when opening enrollment on a cabin-less session — are evaluated as state checks within their respective transitions.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return a `201 Created` status code. Operations that modify an existing resource — including the state-transition endpoints and the clock-setting capability — return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | CampDirector |
| POST | `/guardians/register` | Register a new Guardian account | Anonymous |
| GET | `/guardians/{id}` | Get a Guardian | Guardian, CampDirector |
| POST | `/camps` | Create a Camp | CampDirector |
| GET | `/camps/{id}` | Get a Camp | Guardian, CampDirector, InfirmaryNurse |
| PATCH | `/camps/{id}` | Update Camp configuration | CampDirector |
| POST | `/camps/{id}/sessions` | Create a Session under a Camp | CampDirector |
| GET | `/camps/{id}/sessions` | List Sessions for a Camp | Guardian, CampDirector, InfirmaryNurse |
| GET | `/sessions/{id}` | Get a Session | Guardian, CampDirector, InfirmaryNurse |
| POST | `/sessions/{id}/open-enrollment` | Move a Session from PLANNING to ENROLLING | CampDirector |
| POST | `/sessions/{id}/start` | Move a Session from ENROLLING to RUNNING; expire waitlists | CampDirector |
| POST | `/sessions/{id}/close` | Move a Session from RUNNING to CLOSED | CampDirector |
| POST | `/sessions/{id}/run-intake` | Expire stale offers, then promote waitlisted applicants | CampDirector |
| POST | `/sessions/{id}/cabins` | Create a Cabin under a Session | CampDirector |
| GET | `/sessions/{id}/cabins` | List Cabins for a Session | Guardian, CampDirector, InfirmaryNurse |
| GET | `/cabins/{id}` | Get a Cabin | Guardian, CampDirector, InfirmaryNurse |
| POST | `/cabins/{id}/assign-bunk` | Assign an application's camper to a bunk in this cabin | CampDirector |
| POST | `/camps/{id}/staff` | Create a StaffMember under a Camp | CampDirector |
| GET | `/camps/{id}/staff` | List StaffMembers for a Camp | CampDirector |
| GET | `/staff/{id}` | Get a StaffMember | CampDirector |
| POST | `/cabin-assignments` | Assign a StaffMember to a Cabin | CampDirector |
| GET | `/cabin-assignments` | List CabinAssignments | CampDirector |
| GET | `/cabin-assignments/{id}` | Get a CabinAssignment | CampDirector |
| POST | `/cabin-assignments/{id}/release` | Release a StaffMember from a Cabin | CampDirector |
| POST | `/campers` | Create a Camper owned by the acting Guardian | Guardian |
| GET | `/campers` | List Campers | Guardian, CampDirector |
| GET | `/campers/{id}` | Get a Camper | Guardian, CampDirector, InfirmaryNurse |
| POST | `/health-forms` | Create a DRAFT HealthForm for a camper | Guardian |
| GET | `/health-forms` | List HealthForms | Guardian, CampDirector, InfirmaryNurse |
| GET | `/health-forms/{id}` | Get a HealthForm | Guardian, CampDirector, InfirmaryNurse |
| POST | `/health-forms/{id}/submit` | Submit or resubmit a HealthForm | Guardian |
| POST | `/health-forms/{id}/clear` | Clear a submitted HealthForm | InfirmaryNurse |
| POST | `/health-forms/{id}/flag` | Flag a submitted HealthForm for correction | InfirmaryNurse |
| POST | `/applications` | Create a DRAFT Application | Guardian |
| GET | `/applications` | List Applications | Guardian, CampDirector, InfirmaryNurse |
| GET | `/applications/{id}` | Get an Application | Guardian, CampDirector, InfirmaryNurse |
| POST | `/applications/{id}/submit` | Submit a DRAFT Application | Guardian |
| POST | `/applications/{id}/pay-deposit` | Pay the deposit on an OFFERED application | Guardian |
| POST | `/applications/{id}/enroll` | Enroll a deposit-paid application | CampDirector |
| POST | `/applications/{id}/withdraw` | Withdraw an application | Guardian |
| POST | `/applications/{id}/pay-balance` | Pay the remaining balance | Guardian |
| POST | `/financial-aid` | Request a financial-aid award | Guardian |
| GET | `/financial-aid` | List FinancialAidAwards | Guardian, CampDirector |
| GET | `/financial-aid/{id}` | Get a FinancialAidAward | Guardian, CampDirector |
| POST | `/financial-aid/{id}/approve` | Approve an aid request | CampDirector |
| POST | `/financial-aid/{id}/deny` | Deny an aid request | CampDirector |
| POST | `/financial-aid/{id}/revoke` | Revoke a previously approved award | CampDirector |
| GET | `/payments` | List Payments | Guardian, CampDirector |
| GET | `/payments/{id}` | Get a Payment | Guardian, CampDirector |
| POST | `/sessions/{id}/activities` | Create an ActivityOffering under a Session | CampDirector |
| GET | `/sessions/{id}/activities` | List ActivityOfferings for a Session | Guardian, CampDirector, InfirmaryNurse |
| GET | `/activities/{id}` | Get an ActivityOffering | Guardian, CampDirector, InfirmaryNurse |
| POST | `/activity-enrollments` | Book a camper into an elective | Guardian |
| GET | `/activity-enrollments` | List ActivityEnrollments | Guardian, CampDirector |
| GET | `/activity-enrollments/{id}` | Get an ActivityEnrollment | Guardian, CampDirector |
| POST | `/activity-enrollments/{id}/drop` | Drop an elective booking | Guardian |
| POST | `/canteen-accounts` | Open a canteen account for an application | Guardian, CampDirector |
| GET | `/canteen-accounts` | List CanteenAccounts | Guardian, CampDirector |
| GET | `/canteen-accounts/{id}` | Get a CanteenAccount | Guardian, CampDirector |
| POST | `/canteen-accounts/{id}/transactions` | Record a DEPOSIT or PURCHASE transaction | Guardian, CampDirector |
| GET | `/canteen-accounts/{id}/transactions` | List CanteenTransactions for an account | Guardian, CampDirector |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENTIAL_MISMATCH` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_ENROLLMENT_CLOSED` | 409 Conflict |
| `ERR_NO_CABINS` | 409 Conflict |
| `ERR_SESSION_FULL` | 409 Conflict |
| `ERR_SESSION_NOT_STARTED` | 422 Unprocessable Entity |
| `ERR_SESSION_NOT_ENDED` | 422 Unprocessable Entity |
| `ERR_SESSION_UNDERSTAFFED` | 422 Unprocessable Entity |
| `ERR_SESSION_RUNNING_NO_WITHDRAW` | 409 Conflict |
| `ERR_VISITING_DAY_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_HEALTH_FORM_MISSING` | 422 Unprocessable Entity |
| `ERR_EPIPEN_REQUIRED` | 422 Unprocessable Entity |
| `ERR_HEALTH_NOT_CLEARED` | 422 Unprocessable Entity |
| `ERR_SWIM_TEST_REQUIRED` | 422 Unprocessable Entity |
| `ERR_NO_ELIGIBLE_CABIN` | 422 Unprocessable Entity |
| `ERR_CABIN_GENDER_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CABIN_AGE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CABIN_FULL` | 409 Conflict |
| `ERR_CABIN_UNDERSTAFFED` | 422 Unprocessable Entity |
| `ERR_NO_BUNK_ASSIGNED` | 409 Conflict |
| `ERR_STAFF_NOT_CLEARED` | 422 Unprocessable Entity |
| `ERR_DEPOSIT_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_OFFER_EXPIRED` | 409 Conflict |
| `ERR_AID_EXCEEDS_TUITION` | 422 Unprocessable Entity |
| `ERR_ACTIVITY_TIME_CONFLICT` | 422 Unprocessable Entity |
| `ERR_ACTIVITY_FULL` | 409 Conflict |
| `ERR_CANTEEN_INSUFFICIENT_FUNDS` | 422 Unprocessable Entity |
