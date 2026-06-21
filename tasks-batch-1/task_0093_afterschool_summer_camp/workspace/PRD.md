# Afterschool & Summer Camp Registration API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for a registration and billing platform serving after-school programs and summer camps. The platform exists to solve a recurring operational headache for program operators: how to seat the right children into the right weeks, in the right age groups, with all of their safety paperwork in order, while keeping a coherent running bill in front of every parent. Seats are scarce and demand is seasonal, so the system treats weekly capacity as a strictly allocated resource — every confirmed seat is accounted for, waitlists form automatically when a week fills, and a freed seat is handed to the next family in line without manual intervention.

The platform serves three working populations. Parents and legal guardians register their children, attach the medical and pickup authorizations and emergency contacts that camps are legally required to hold, request need-based scholarships, and enroll children week by week. Program directors build the catalog of programs, age-grouped sessions, and the individual weeks within each session; they review authorizations and scholarships, and they manage the disruption of rainy days by relocating outdoor groups to indoor alternates. Billing administrators close out the running drafts into finalized invoices and record payments. Because a single enrollment touches capacity, eligibility, safety paperwork, scheduling conflicts, scholarships, and a shared household invoice all at once, the system's central design goal is that these derived figures — seat counts, waitlist ranks, line tuitions, and invoice totals — never drift out of agreement with the underlying enrollments that produced them.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that govern every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers that together establish the caller's identity and operational capacity: `X-User-ID` identifies the acting user, and `X-User-Role` declares the role under which they are acting. A request to a protected endpoint that is missing either header, or that carries a malformed value, is rejected with `ERR_UNAUTHENTICATED`. When a caller is authenticated but their role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes four roles, spelled exactly as follows: `Anonymous`, `Guardian`, `ProgramDirector`, and `BillingAdmin`.

`Anonymous` represents an unauthenticated caller. Its identity is opaque: when `X-User-Role` is `Anonymous`, `X-User-ID` (if present at all) is not tied to any persisted entity and is never compared to a stored `id`. The only operation available to `Anonymous` is registering a new guardian.

`Guardian` is the parent or legal guardian. This role is entity-backed: when `X-User-Role` is `Guardian`, `X-User-ID` is the `id` of the acting `Guardian` record. Ownership checks on any resource that references a guardian compare that resource's owning-guardian linkage to `X-User-ID`. Concretely, a child carries a `guardian_id`, and any resource hanging off that child — its enrollments, authorization forms, emergency contacts, scholarship requests — is owned by the guardian named in `guardian_id`. When a guardian acts on a child, enrollment, or authorization form they do not own (the owning `Guardian.id` does not equal `X-User-ID`), the request is rejected with `ERR_NOT_RESOURCE_OWNER`.

`ProgramDirector` operates the catalog and review functions — programs, sessions, weekly offerings, weather declarations, authorization approvals, and scholarship review. Its identity is opaque: when `X-User-Role` is `ProgramDirector`, `X-User-ID` is an operator identifier not tied to any persisted entity; the server may record it on an audit trail (see the `actor_role` discussion below) but does not compare it to any entity's `id`. `BillingAdmin` finalizes and voids invoices and records payments; its identity is likewise opaque and not compared to any entity `id`.

Every state-changing operation appends an audit record. Each such record captures the `entity_type` and `entity_id` of the resource whose transition was recorded (the `entity_id` is an identity reference only, never treated as a foreign key), an `action` label describing the transition, and the `actor_role` taken from the request's `X-User-Role`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter sets the maximum number of items returned; if omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

List responses include these four fields in the `meta` object: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most resources in this system are first-class records that expose a standard set of system-managed fields:

- **`id`** — a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at`** — an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was first created.
- **`updated_at`** — an ISO 8601 UTC timestamp recording the most recent modification; it is refreshed on any change to the resource.
- **`version`** — a system-managed integer that starts at creation and increments by one on every mutation of the resource. It is the basis for optimistic concurrency control described in §2.9.

`Guardian`, `Child`, `EmergencyContact`, `AuthorizationForm`, `Program`, `Session`, `WeeklyOffering`, `ScholarshipAward`, `Enrollment`, and `Invoice` all carry the full set above. Three records are deliberately lighter: a `Payment`, a `WeatherEvent`, and an `AuditEntry` are immutable once written, so each carries only an `id` and a `created_at` — they have neither an `updated_at` nor a `version` field, and nothing in the system mutates them after creation.

When the server itself advances a resource — for example, recomputing a weekly offering's counts after an enrollment, or re-pricing invoice lines after a scholarship decision — that recomputation is a mutation: the affected resource's `updated_at` is refreshed and its `version` is incremented, exactly as a client-initiated change would do.

### 2.5. Derived-Field Reconciliation and Cascade Consistency

A defining characteristic of this platform is that many of the numbers a user sees are *derived* — they are not stored independently but recomputed from the enrollments and awards beneath them. A weekly offering's `enrolled_count`, `waitlist_count`, and `capacity_state` are derived from its enrollments; an enrollment's `waitlist_rank`, `provisional_tuition_cents`, and `final_tuition_cents` are derived from pricing rules; an invoice's `subtotal_cents`, `sibling_discount_cents`, and `total_due_cents` are derived from its confirmed lines. Whenever an operation changes the underlying facts, the system re-runs the relevant reconciliation so these derived values stay in agreement, and it does so immediately within the same operation rather than on a delayed schedule.

These reconciliations frequently chain. A single user action can ripple outward through several entities — a seat freed by a withdrawal can promote a waitlisted child, which creates a new invoice line, which changes an invoice subtotal, which changes the household sibling discount, which changes the amount due. The business-logic sections in §3 describe each such chain in full; the principle here is that the system is responsible for carrying every link of a cascade to completion before the originating request returns, so that no parent is left holding stale totals after a child changes.

### 2.6. Reference Integrity and Nested Lookups

Several read endpoints expose a parent's dependents by walking a foreign-key relationship in reverse — for example, listing the children of a guardian, the sessions of a program, the weekly offerings of a session, or the enrollments of a weekly offering. For any request whose path names a resource, the system validates that resource's existence before proceeding; when an identifier in the path or body refers to something that does not exist, the request is rejected with `ERR_NOT_FOUND`. When a path carries more than one identifier, they are validated left to right, and the first missing one produces the `ERR_NOT_FOUND` rejection.

### 2.7. Monetary Precision and Rounding

All money in this system is expressed and stored as an integer number of cents; there are no fractional-cent values. Where a rule multiplies a cent amount by a fraction — such as applying a scholarship discount or a sibling discount — the result is rounded to a whole number of cents using the round-half-up convention (a value exactly at the halfway point rounds up). The precise point at which rounding is applied within each formula is pinned in the §3 narratives, because the order of "scale, then round, then add" versus "add, then round" changes the cent total; implementers must follow the order stated for each calculation. Scholarship discount percentages are the only fractional figure the system stores: an `approved_discount_pct` is a fraction between 0 and 1 inclusive carried to at most two decimal places.

### 2.8. Capacity and Allocation Principle

Each session declares a `weekly_capacity` — the maximum number of `CONFIRMED` enrollments allowed in any one of its weekly offerings. Capacity is the scarce resource the platform allocates. An offering is `AVAILABLE` while its confirmed count is below its session's `weekly_capacity` and `FULL` once the confirmed count reaches or exceeds it. New enrollment requests resolve against live capacity: a request that arrives while a seat remains is confirmed, and one that arrives when the week is full is waitlisted. Because seat counts are derived and can move between the moment a client reads an offering and the moment it submits an enrollment, capacity decisions are protected by the concurrency control described next.

### 2.9. Optimistic Concurrency Control

Two write operations require the client to declare the version it last observed of a parent record, so the server can refuse to act on a stale view.

Creating an enrollment requires an `expected_weekly_offering_version` field carrying the client's last observed `version` of the target `WeeklyOffering`. If the offering's current `version` no longer matches that value — because another guardian's enrollment has since taken the last seat, legitimately flipping the offering to `FULL` and bumping its version — the create is rejected with `ERR_STALE_OFFERING_VERSION` (HTTP 412). This prevents a client from over-filling a week against a remaining-seat count it can no longer trust.

Finalizing an invoice requires an `expected_invoice_version` field carrying the client's last observed `version` of the target `Invoice`. A scholarship approval or a sibling withdrawal can re-run the invoice totals and bump the invoice's `version` between the moment the administrator reads it and the moment they finalize; if the supplied `expected_invoice_version` no longer matches the invoice's current `version`, the finalize is rejected with `ERR_STALE_INVOICE_VERSION` (HTTP 412), so the administrator never locks obsolete totals. Endpoints other than these two do not take a version field and are not subject to this check.

### 2.10. Validation Ordering

When several checks guard one operation, they are evaluated in a fixed priority order so that the same failing request always yields the same error. Across the API the global ordering is: first authentication of the request headers (`ERR_UNAUTHENTICATED`), then role authorization for the operation (`ERR_FORBIDDEN_ROLE`), then existence of every referenced resource (`ERR_NOT_FOUND`), then guardian ownership of the referenced child/enrollment/form (`ERR_NOT_RESOURCE_OWNER`), then the target resource being in a legal state for the requested transition (`ERR_INVALID_STATE`), then the operation's own business rules, and finally the structural well-formedness of the request body (`ERR_INVALID_REQUEST`: a required field is missing, an enum value is outside its declared set, or a numeric field is out of its declared bounds). The enrollment endpoint layers a long chain of business rules on top of this skeleton; their internal ordering is spelled out in §3.4.

## 3. Business Logic & Workflows

### 3.1. Building the Catalog: Programs and Sessions

A `ProgramDirector` lays the foundation by creating a **Program**, supplying its `name`, its `program_type`, and the inclusive whole-year age band the program serves via `min_age` and `max_age`. A program's type is one of `AFTERSCHOOL` or `CAMP`; the two differ in how their weeks are priced, as §3.6 explains. The age band must be coherent — `max_age` must be at least `min_age` — and a band where the minimum exceeds the maximum is rejected with `ERR_INVALID_AGE_RANGE`. A program begins life in `DRAFT`.

Inside a program, the director defines **Sessions**, each an age-grouped offering bucket. A session carries its parent `program_id`, a `title`, the inclusive age group it serves via `age_group_min` and `age_group_max`, an `age_as_of_date` (the reference date on which a child's age is judged for this session), a `weekly_capacity`, and a `base_weekly_tuition_cents` list price per enrolled week before any discount. The session's age group must sit within the program's band: `age_group_min` must be at least the program's `min_age`, and `age_group_max` must be at most the program's `max_age` and not below `age_group_min`. A session group that falls outside its program's range is rejected with `ERR_INVALID_AGE_RANGE`. A new session starts in `SCHEDULED`.

A program moves from `DRAFT` to `PUBLISHED` only when it holds at least one session in `SCHEDULED` or `OPEN`; a publish attempt against a program with no such session is rejected with `ERR_NO_SESSION_FOR_PUBLISH`, and the program's age band must additionally be coherent (`min_age` not above `max_age`). Publishing records a `PROGRAM_PUBLISHED` audit action and increments the program's version. A `PUBLISHED` program may later be retired to the terminal `ARCHIVED` state, but only when none of its sessions is `OPEN`; archiving records a `PROGRAM_ARCHIVED` action and bumps the version. Attempting either transition from a state that does not permit it yields `ERR_INVALID_STATE`.

### 3.2. Opening Sessions and Laying Out Weeks

Before families can enroll, a director opens a session, advancing it `SCHEDULED → OPEN`. Opening is gated on two conditions: the parent program must already be `PUBLISHED` — an attempt to open under an unpublished program is rejected with `ERR_PROGRAM_NOT_PUBLISHED` — and the session must already have at least one weekly offering laid out beneath it. Opening records a `SESSION_OPENED` audit action and increments the session's version. A director may later move an `OPEN` session to `CLOSED`; closing records `SESSION_CLOSED`, bumps the version, and means that any subsequent enrollment request against any week of that session is refused with `ERR_SESSION_NOT_OPEN`.

A session may be cancelled from either `SCHEDULED` or `OPEN`, landing in the terminal `CANCELLED` state. Cancellation is consequential and triggers a three-link cascade. First, for every weekly offering under the session, every enrollment currently in `CONFIRMED` or `WAITLISTED` is moved to `WITHDRAWN`. Second, because those withdrawals change the facts beneath each affected offering, each such offering re-runs its count reconciliation, dropping `enrolled_count` and `waitlist_count` accordingly. Third, because those withdrawn lines belonged to draft invoices, each affected `DRAFT` invoice re-runs its totals so that `subtotal_cents`, `sibling_discount_cents`, and `total_due_cents` fall to reflect the lost lines. Cancellation records a `SESSION_CANCELLED` action and increments the session's version. A cancel requested from any state other than `SCHEDULED` or `OPEN` is rejected with `ERR_INVALID_STATE`.

The director builds the calendar by creating **Weekly Offerings** under a session, each carrying its parent `session_id` and a `week_start` — the ISO date of the Monday that opens the enrollment week, which spans the seven-day window beginning at that Monday and ending the moment the following Monday begins (the start day is included; the next Monday is not). At creation the director may also name a `rain_alternate_offering_id` — the indoor offering to which this week's children are moved on a rain day — though this may be left unset and configured later. A fresh offering's weather posture is `NORMAL`, its `enrolled_count` and `waitlist_count` are zero, and its `capacity_state` is `AVAILABLE`. A director may configure or change the rain alternate after creation through a dedicated update; because that update mutates the offering, it requires the offering's `expected_weekly_offering_version` and sets `rain_alternate_offering_id`, incrementing the version on success.

### 3.3. The Family Side: Children, Contacts, and Authorizations

A prospective family begins as a **Guardian**, registered by an anonymous caller with an `email` (the login identity, which must be unique among guardians when compared case-insensitively and must be non-empty), a `full_name`, a `phone`, and a `home_zip` of exactly five digits (used later for residency-based scholarship eligibility). A guardian then registers one or more **Children**, each created under the acting guardian via `guardian_id`, with a `first_name`, a `birth_date` (the ISO date of birth that drives all age computation), and an optional `household_size` — the number of people in the household, which feeds scholarship income-tier eligibility, defaults to 1, and must be at least 1. A child's `age_years` is never supplied; it is computed on demand against a session's reference date as described in §3.4.

Camps may not seat a child whose safety paperwork is incomplete, so a guardian must lodge the right records before enrolling. Each child needs at least one **Emergency Contact**, created with the child's `child_id`, a `contact_name`, a `contact_phone`, and the `relationship` to the child (for instance, grandparent or neighbor). A guardian also submits **Authorization Forms** for the child, each carrying the `child_id` and a `form_type` of either `MEDICAL` or `PICKUP`. A `MEDICAL` form records allergy and medication directives in `medication_notes` (which is null on a `PICKUP` form), while a `PICKUP` form lists the people permitted to collect the child in `authorized_pickup_names` (an array that is empty on a `MEDICAL` form). A new form is `SUBMITTED`.

A `ProgramDirector` reviews submitted forms and advances them `SUBMITTED → APPROVED`. Approval is gated by content appropriate to the form's type: a `MEDICAL` form may be approved only when its `medication_notes` is non-empty, and a `PICKUP` form only when its `authorized_pickup_names` array is non-empty; approval records an `AUTH_APPROVED` action and bumps the form's version. The owning guardian may revoke a form, moving it to the terminal `REVOKED` state from either `SUBMITTED` or `APPROVED`; revocation from an `APPROVED` form records an `AUTH_REVOKED` action and increments the version, and in both revocation paths the acting guardian must own the form's child. A revoke attempted on a form already `REVOKED`, or an approve attempted on a form not `SUBMITTED`, is rejected with `ERR_INVALID_STATE`.

A guardian may also request a **Scholarship Award** for a child, supplying the `child_id` and a requested `tier` of `NONE`, `PARTIAL`, or `FULL`; the award begins `REQUESTED` with an `approved_discount_pct` of 0. A director approves it (`REQUESTED → APPROVED`), denies it (`REQUESTED → DENIED`, terminal), or — for an already-approved award — revokes it (`APPROVED → REVOKED`, terminal). The pricing and cascade consequences of these scholarship transitions are detailed in §3.6.

### 3.4. Enrolling a Child: Branch, Eligibility, and the Waitlist

Enrollment is the heart of the platform. A guardian enrolls a child into a specific week by submitting the child's `child_id`, the target `weekly_offering_id`, and the `expected_weekly_offering_version` that pins the offering version the client last saw. The system itself decides the resulting branch — there is no separate "confirm" or "waitlist" call — by comparing the offering's live confirmed count against its session's `weekly_capacity`: when a seat is available the enrollment lands `CONFIRMED`, and when the week is already full it lands `WAITLISTED`. Both branches share the same gauntlet of preconditions; only the seat-availability check separates them.

Those preconditions are evaluated in the following order, each producing its own error. The acting guardian must own the child (the child's `guardian_id` must equal `X-User-ID`), or the request is rejected with `ERR_NOT_RESOURCE_OWNER`. The target week's parent session must be `OPEN`; otherwise `ERR_SESSION_NOT_OPEN`. The week's `weather_state` must be `NORMAL` — a week that has been rained out cannot accept new enrollments — or the request fails with `ERR_OFFERING_RAINED_OUT`. The child must hold both an `APPROVED` authorization form of type `MEDICAL` and an `APPROVED` form of type `PICKUP`; lacking either yields `ERR_AUTHORIZATION_INCOMPLETE`. The child must have at least one emergency contact on file, or `ERR_NO_EMERGENCY_CONTACT`. The child's age, computed as of the session's reference date, must fall within the session's age group; an age outside the group yields `ERR_AGE_OUT_OF_GROUP`. There must be no existing non-`WITHDRAWN` enrollment for the same child-and-week pair, or the request is a duplicate and is rejected with `ERR_DUPLICATE_ENROLLMENT`. The child must not already hold a `CONFIRMED` or `WAITLISTED` enrollment in another weekly offering whose seven-day week window overlaps this one — a child cannot be in two camps the same week, though enrolling in strictly adjacent weeks (the very next Monday, with no overlap) is permitted — and a clash yields `ERR_WEEK_OVERLAP_CHILD`. Finally, the supplied `expected_weekly_offering_version` must match the offering's current `version`, or the request is rejected with `ERR_STALE_OFFERING_VERSION` as described in §2.9.

The age computation works in whole years measured to the session's reference date. Take the reference year minus the birth year; then, if the reference date's month-and-day falls before the child's birth month-and-day, subtract one year because the birthday has not yet been reached on the reference date. The child is eligible when the resulting whole-year age is at least the session's `age_group_min` and at most its `age_group_max`. This same computation is also available as a read-only eligibility check: a caller may ask for a child's age against a particular session by supplying that `session_id`, and the system returns the child with the computed age without changing anything.

When an enrollment is confirmed, several effects fire together. The enrollment's `status` becomes `CONFIRMED`. The offering re-runs its count reconciliation so `enrolled_count` rises by one and `capacity_state` is recomputed. A provisional line tuition is computed and stored on `provisional_tuition_cents` (the formula is in §3.6). The enrollment is attached to the guardian's `DRAFT` invoice for the offering's billing period — creating that invoice if none exists yet — and recorded on the enrollment's `invoice_id`; that invoice then re-runs its totals and its sibling discount. The action is audited as `ENROLLMENT_CONFIRMED`, and the offering's version is incremented.

When an enrollment is waitlisted instead, its `status` becomes `WAITLISTED`, the offering's reconciliation raises `waitlist_count` by one, and the new enrollment receives a `waitlist_rank` equal to its position among waitlisted siblings ordered by creation time ascending (so the first to join holds rank 1). No invoice line is created while an enrollment is waitlisted, and its `provisional_tuition_cents` stays at 0. The action is audited as `ENROLLMENT_WAITLISTED` and the offering's version is incremented.

A guardian may withdraw their child's enrollment, moving it to the terminal `WITHDRAWN` state. A `CONFIRMED` enrollment can be withdrawn only while its invoice is still `DRAFT`; an attempt to withdraw a seat whose invoice has already been billed is rejected with `ERR_ENROLLMENT_BILLED`. Withdrawing a confirmed seat triggers a three-link cascade. First, the offering's reconciliation decrements `enrolled_count`, freeing a seat. Second, if any enrollment is waitlisted on that offering, the head of the line — the one with the lowest `waitlist_rank`, equivalently the earliest by creation time — is automatically promoted from `WAITLISTED` to `CONFIRMED`, has its `waitlist_rank` cleared to null, and is given a freshly computed `provisional_tuition_cents` and a draft invoice line. Third, the promoted enrollment's invoice re-runs its totals and sibling discount, while the withdrawn enrollment's line is removed from its own invoice and that invoice is re-totaled. The withdrawal is audited as `ENROLLMENT_WITHDRAWN` and the offering's version is incremented; the reconciliation also re-ranks whatever waitlisted enrollments remain. A waitlisted enrollment may itself be withdrawn directly; doing so lowers `waitlist_count` and re-ranks the remaining waitlisted enrollments by creation time ascending. Withdrawing from a state that is neither `CONFIRMED` nor `WAITLISTED` is rejected with `ERR_INVALID_STATE`, and the guardian must own the child in either path.

### 3.5. Rainy Days: Relocating Outdoor Weeks

Outdoor weeks need an indoor fallback. A `ProgramDirector` declares a rain day on an outdoor offering by naming the affected `weekly_offering_id`; this advances that offering's weather dimension `NORMAL → RAIN_ACTIVATED`, a posture that runs independently of the occupancy posture (`AVAILABLE`/`FULL`) on the same offering. A rain declaration is permitted only when the offering is currently `NORMAL`, has a configured `rain_alternate_offering_id`, and belongs to a session that is `OPEN`; an offering in the wrong weather state is rejected with `ERR_INVALID_STATE`.

Before any child is moved, two guard rails are checked. Every relocating child's age must fit the alternate offering's age group; if any confirmed child's age falls outside the alternate's group, the entire declaration is rejected with `ERR_ALTERNATE_AGE_MISMATCH` before a single relocation occurs. The number of confirmed children to relocate may exceed the alternate offering's `weekly_capacity` by at most one — a hard overflow tolerance that protects the indoor room — so if the relocate count is greater than the alternate's capacity plus one, the declaration is rejected with `ERR_ALTERNATE_OVER_CAPACITY` before any relocation occurs.

When the declaration passes, a two-link cascade runs. First, every `CONFIRMED` enrollment on the source offering is re-pointed to the alternate, in creation-time-ascending order, by changing each enrollment's `weekly_offering_id` to the `rain_alternate_offering_id`. Children that fit within the alternate's capacity remain `CONFIRMED` there; any that overflow the alternate's `weekly_capacity` are placed `WAITLISTED` on the alternate but are still relocated. Second, both the source and the alternate offerings re-run their count reconciliation, moving `enrolled_count` between them. The system records a **Weather Event** capturing the affected `weekly_offering_id`, a server-stamped `declared_at`, and a `moved_enrollment_count` equal to the number of children relocated; the transition is audited as `RAIN_ACTIVATED`, and the version of both offerings is incremented.

Clearing rain advances the weather dimension `RAIN_ACTIVATED → NORMAL`, which only resets the weather posture so a future rain day can fire again — the cycle is repeatable. Children moved by the prior rain activation stay on the alternate; there is no automatic return. Clearing is audited as `RAIN_CLEARED` and increments the offering's version. The system also exposes, for any offering, the list of other offerings that name it as their rain alternate.

### 3.6. Pricing a Week, Scholarships, and the Household Discount

The price of a single enrolled week is computed by a shared rule with two variants. Start from the session's `base_weekly_tuition_cents`. Apply the child's scholarship discount as a multiplicative reduction: multiply the base by one minus the child's `approved_discount_pct` (taken from the child's `APPROVED` scholarship award, or 0 when the child has none), and round that scaled amount to whole cents using round-half-up. Then, and only then, add the program-type surcharge: a `CAMP` program adds a flat materials surcharge of 1,500 cents per enrolled week on top of the scholarship-reduced amount, while an `AFTERSCHOOL` program adds nothing. The rounding order is pinned: scale by the discount and round first, then add the surcharge — never the reverse. The final line amount is floored at 0. The **provisional** variant uses the child's discount as it stands at calculation time and is written to `provisional_tuition_cents` while the invoice is `DRAFT`; it is recomputed by later cascades. The **final** variant snapshots the discount at the moment the invoice is finalized, writes it to `final_tuition_cents`, and freezes it, so subsequent scholarship changes no longer move it.

Scholarship discount percentages come from a fixed tier table, locked onto `approved_discount_pct` at approval: `NONE` maps to 0, `PARTIAL` maps to 0.5 (half off), and `FULL` maps to 1.0 (the full base waived). An approval is permitted only from a `REQUESTED` award whose `tier` is not `NONE`; an approve from any other state is rejected with `ERR_INVALID_STATE`. Approving an award (audited as `SCHOLARSHIP_APPROVED`, version incremented) triggers a three-link cascade for the awarded child: first, every `DRAFT` invoice that holds a `CONFIRMED` enrollment for that child re-runs the provisional line price on those lines with the newly locked discount; second, each touched line's new `provisional_tuition_cents` feeds the invoice's subtotal, lowering `subtotal_cents`; third, the invoice re-derives `total_due_cents` from the new subtotal and the current sibling discount. Denying an award simply moves it to `DENIED` (audited `SCHOLARSHIP_DENIED`, version incremented). Revoking an approved award is permitted only when no invoice that references this child's enrollments is `FINALIZED`, `PAID`, or `VOID`; on revocation the award goes to `REVOKED`, `approved_discount_pct` resets to 0, and a compensating re-price restores each `DRAFT` invoice line for the child to its undiscounted `provisional_tuition_cents`, after which each touched invoice re-runs its totals — so revoking an approval returns the books exactly to where they would have stood without it. Revocation is audited as `SCHOLARSHIP_REVOKED` and increments the version.

The **household sibling discount** rewards families enrolling more than one child on the same invoice. It is computed over the `CONFIRMED` enrollments of a single draft invoice, grouped by child. Count the distinct children among those confirmed lines: if fewer than two distinct children appear, `sibling_discount_cents` is 0. Otherwise, identify the anchor child — the one whose single most expensive provisional line is the largest of all the children's (ties broken by the lowest child creation time) — and exclude that anchor; every other distinct child is eligible. For each eligible child, take that child's single highest `provisional_tuition_cents` line on this invoice. Sum those per-child highest lines across all eligible children, multiply the sum by the sibling discount rate of 0.10 (ten percent), and round the single summed product half-up to whole cents — the rounding happens once on the total, not per child. The result is `sibling_discount_cents`.

Invoice totals are derived in a pinned order whenever a draft invoice's confirmed lines change: first the per-line tuitions, then the sibling discount, then the invoice totals. For a `DRAFT` invoice, `subtotal_cents` is the sum of `provisional_tuition_cents` across its `CONFIRMED` enrollment lines (waitlisted and withdrawn lines contribute nothing); for a `FINALIZED` or `PAID` invoice it is the frozen sum of `final_tuition_cents` over those lines. In every case `total_due_cents` is the subtotal minus `sibling_discount_cents`, floored at 0.

### 3.7. Billing: Finalizing, Paying, and Voiding

An **Invoice** is the running bill for one guardian across one billing period. It carries the billed `guardian_id` and a `billing_period` label such as a year-and-week tag, and there is one draft invoice per guardian per period. An invoice is created implicitly when a guardian's first confirmed enrollment for a period needs somewhere to land (see §3.4), and it begins in `DRAFT` with an `amount_paid_cents` of 0. While `DRAFT`, its `subtotal_cents`, `sibling_discount_cents`, and `total_due_cents` track the live enrollments beneath it as cascades move them.

A `BillingAdmin` finalizes a draft invoice, advancing it `DRAFT → FINALIZED`, but only when it holds at least one `CONFIRMED` enrollment line; a finalize with zero confirmed lines is rejected with `ERR_NO_CONFIRMED_LINES`, and the request must carry an `expected_invoice_version` matching the invoice's current `version` (failing which it is rejected with `ERR_STALE_INVOICE_VERSION`, per §2.9). On finalization, each confirmed line's `final_tuition_cents` is computed with the final pricing variant and frozen; `subtotal_cents` is re-frozen as the sum of those final line amounts, `sibling_discount_cents` is re-frozen over the frozen lines, and `total_due_cents` is set to the subtotal minus the sibling discount, floored at 0. Finalization is audited as `INVOICE_FINALIZED` and increments the version.

A `BillingAdmin` records **Payments** against a finalized invoice, each carrying the `invoice_id`, an `amount_cents` of at least 1, and a `method` of `CARD`, `ACH`, or `WALLET`. A payment may not exceed the invoice's outstanding balance — the `total_due_cents` minus the `amount_paid_cents` already recorded — and an overpayment is rejected with `ERR_OVERPAYMENT`. Each accepted payment adds its `amount_cents` to the invoice's `amount_paid_cents`; once cumulative payments reach or exceed `total_due_cents`, the invoice advances `FINALIZED → PAID` (audited `INVOICE_PAID`, version incremented). A `DRAFT` invoice may instead be voided to the terminal `VOID` state by a `BillingAdmin` (audited `INVOICE_VOIDED`, version incremented). Finalizing or voiding from a state other than `DRAFT`, or paying an invoice that is not `FINALIZED`, is rejected with `ERR_INVALID_STATE`. The system also exposes the audit trail itself as a filterable list, queryable by `entity_type` and `entity_id`, alongside the per-invoice payment list and the per-guardian invoice list.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including state transitions and configuration updates — return a `200 OK` status code. List and detail reads return `200 OK`. The request bodies, query filters, and side effects for each endpoint are described in the §3 narratives above; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/guardians` | Register a guardian | Anonymous |
| GET | `/guardians/{id}` | Fetch a guardian | Guardian, ProgramDirector, BillingAdmin |
| GET | `/guardians/{id}/children` | List a guardian's children | Guardian, ProgramDirector |
| GET | `/guardians/{id}/invoices` | List a guardian's invoices | Guardian, BillingAdmin |
| POST | `/children` | Create a child under the acting guardian | Guardian |
| GET | `/children/{id}` | Fetch a child | Guardian, ProgramDirector |
| GET | `/children/{id}/age-eligibility` | Compute a child's age against a session | Guardian, ProgramDirector |
| GET | `/children/{id}/emergency-contacts` | List a child's emergency contacts | Guardian, ProgramDirector |
| GET | `/children/{id}/authorization-forms` | List a child's authorization forms | Guardian, ProgramDirector |
| GET | `/children/{id}/scholarship-awards` | List a child's scholarship awards | Guardian, ProgramDirector |
| POST | `/emergency-contacts` | Add an emergency contact for a child | Guardian |
| POST | `/authorization-forms` | Submit a medical or pickup authorization form | Guardian |
| POST | `/authorization-forms/{id}/approve` | Approve a submitted authorization form | ProgramDirector |
| POST | `/authorization-forms/{id}/revoke` | Revoke a child's authorization form | Guardian |
| POST | `/programs` | Create a program (DRAFT) | ProgramDirector |
| GET | `/programs/{id}` | Fetch a program | Guardian, ProgramDirector, BillingAdmin |
| GET | `/programs/{id}/sessions` | List a program's sessions | Guardian, ProgramDirector |
| POST | `/programs/{id}/publish` | Publish a program | ProgramDirector |
| POST | `/programs/{id}/archive` | Archive a published program | ProgramDirector |
| POST | `/sessions` | Create an age-group session under a program | ProgramDirector |
| GET | `/sessions/{id}` | Fetch a session | Guardian, ProgramDirector, BillingAdmin |
| GET | `/sessions/{id}/weekly-offerings` | List a session's weekly offerings | Guardian, ProgramDirector |
| POST | `/sessions/{id}/open` | Open a scheduled session for enrollment | ProgramDirector |
| POST | `/sessions/{id}/close` | Close an open session to new enrollments | ProgramDirector |
| POST | `/sessions/{id}/cancel` | Cancel a session; cascades enrollment withdrawals | ProgramDirector |
| POST | `/weekly-offerings` | Create a weekly offering under a session | ProgramDirector |
| GET | `/weekly-offerings/{id}` | Fetch a weekly offering with computed counts | Guardian, ProgramDirector, BillingAdmin |
| GET | `/weekly-offerings/{id}/rain-dependents` | List offerings that name this one as their rain alternate | Guardian, ProgramDirector |
| GET | `/weekly-offerings/{id}/enrollments` | List an offering's enrollments | Guardian, ProgramDirector, BillingAdmin |
| GET | `/weekly-offerings/{id}/weather-events` | List an offering's weather events | ProgramDirector, BillingAdmin |
| PATCH | `/weekly-offerings/{id}` | Configure the rain alternate for a weekly offering | ProgramDirector |
| POST | `/weekly-offerings/{id}/clear-rain` | Reset a weekly offering's weather posture to NORMAL | ProgramDirector |
| POST | `/weather-events` | Declare a rain day; relocates confirmed children to the alternate | ProgramDirector |
| POST | `/scholarship-awards` | Request a scholarship for a child | Guardian |
| POST | `/scholarship-awards/{id}/approve` | Approve a scholarship; cascades draft-invoice re-pricing | ProgramDirector |
| POST | `/scholarship-awards/{id}/deny` | Deny a scholarship request | ProgramDirector |
| POST | `/scholarship-awards/{id}/revoke` | Revoke an approved scholarship; compensating re-price | ProgramDirector |
| POST | `/enrollments` | Enroll a child into a weekly offering (auto-branches) | Guardian |
| GET | `/enrollments/{id}` | Fetch an enrollment with computed tuition and rank | Guardian, ProgramDirector, BillingAdmin |
| GET | `/enrollments` | List enrollments, filterable by child or invoice | Guardian, ProgramDirector, BillingAdmin |
| POST | `/enrollments/{id}/withdraw` | Withdraw an enrollment; frees a seat, promotes the waitlist head | Guardian |
| GET | `/invoices/{id}` | Fetch an invoice with computed totals | Guardian, BillingAdmin |
| GET | `/invoices/{id}/payments` | List payments against an invoice | Guardian, BillingAdmin |
| POST | `/invoices/{id}/finalize` | Finalize a draft invoice; freeze final tuition and totals | BillingAdmin |
| POST | `/invoices/{id}/void` | Void a draft invoice | BillingAdmin |
| POST | `/payments` | Record a payment against a finalized invoice | BillingAdmin |
| GET | `/audit-entries` | List audit entries, filterable by entity | ProgramDirector, BillingAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SESSION_NOT_OPEN` | 409 |
| `ERR_OFFERING_RAINED_OUT` | 409 |
| `ERR_AUTHORIZATION_INCOMPLETE` | 422 |
| `ERR_NO_EMERGENCY_CONTACT` | 422 |
| `ERR_AGE_OUT_OF_GROUP` | 422 |
| `ERR_DUPLICATE_ENROLLMENT` | 409 |
| `ERR_WEEK_OVERLAP_CHILD` | 409 |
| `ERR_ALTERNATE_AGE_MISMATCH` | 422 |
| `ERR_ALTERNATE_OVER_CAPACITY` | 409 |
| `ERR_ENROLLMENT_BILLED` | 409 |
| `ERR_OVERPAYMENT` | 422 |
| `ERR_STALE_OFFERING_VERSION` | 412 |
| `ERR_STALE_INVOICE_VERSION` | 412 |
| `ERR_NO_CONFIRMED_LINES` | 409 |
| `ERR_PROGRAM_NOT_PUBLISHED` | 409 |
| `ERR_NO_SESSION_FOR_PUBLISH` | 409 |
| `ERR_INVALID_AGE_RANGE` | 400 |
| `ERR_INVALID_REQUEST` | 400 |
