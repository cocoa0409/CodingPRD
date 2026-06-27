# Dance Studio Recital API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Dance Studio & Recital Management API, the operational backbone of a multi-discipline dance studio. The platform reconciles three concerns that, in practice, pull against one another: the studio's scheduling reality (rooms, instructors, weekly sessions, and term calendars), the household economics of recurring tuition (sibling and multi-class discounts, auto-pay, account credit, and delinquency), and the event logistics that bookend a term (costume sizing and ordering, recital ticketing with assigned seats, and competition-team travel). A single parent action — confirming an enrollment, dropping a class, holding a seat — can ripple through capacity counts, waitlist ordering, discount tiers, and a family's open invoice. The API exists to make those ripples deterministic.

Three constituencies share the system. Studio administrators own the configuration spine: terms, rooms, instructors, sections and their sessions, costumes, recitals, teams, trips, and the invoicing engine. Instructors own attendance for the sessions they teach. Parents — each backed by a family account — manage their own students, enrollments, costume sizing, ticket purchases, and trip signups, and never reach across into another family's records. Because billing, placement, and ticketing all interlock, the system treats every mutation as immediately consistent: derived counts, discount-adjusted charges, family wallet balances, and parent/child statuses are reconciled within the same request that triggers them, never deferred to a later sweep.

A logical clock drives every time-sensitive rule — invoice due dates, the costume sizing window, recital completion eligibility, and the makeup-attendance window. The clock is explicit and test-driven rather than wall-clock, so the studio's billing and deadline behavior is fully reproducible.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response conventions, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes four roles, spelled exactly: `StudioAdmin`, `Instructor`, `Parent`, and `Anonymous`. A request that omits `X-User-Role`, or carries a value outside this set, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is recognized but not permitted for the targeted endpoint is rejected with `ERR_FORBIDDEN_ROLE`. The `Anonymous` role is accepted only on the family self-registration endpoint; everywhere else an `Anonymous` (or header-less) request is unauthenticated.

The `StudioAdmin` role is an opaque operator identity: when `X-User-Role` is `StudioAdmin`, `X-User-ID` is an operator identifier not tied to any persisted entity. The server does not compare it to any entity's `id`, and a `StudioAdmin` may act on behalf of any family. The `Anonymous` role is likewise opaque and tied to no entity.

The `Instructor` role is entity-backed: when `X-User-Role` is `Instructor`, `X-User-ID` is the `id` of the acting `Instructor`. The `Parent` role is entity-backed against the family: when `X-User-Role` is `Parent`, `X-User-ID` is the `id` of the acting `Family`. Ownership checks for a `Parent` compare the owning `Family.id` of the targeted resource to `X-User-ID`. Concretely, a `Parent` may only act on a `Student`, `Enrollment`, `SeatAssignment`, `CostumeOrder`, `Invoice`, or `Family` whose owning family is their own; an attempt to act on another household's resource is rejected with `ERR_NOT_RESOURCE_OWNER`. For an `Enrollment`, the owning family is the enrollment's `family_id`; for a `Student`, it is the student's `family_id`; for a `SeatAssignment`, it is the seat's `family_id`. This `ERR_NOT_RESOURCE_OWNER` gate applies to single-resource fetches and state transitions; collection list endpoints do not raise it. Of the list endpoints, only `GET /invoices` silently restricts a `Parent`'s results to their own `family_id`; the other list endpoints apply only their declared query-parameter filters and do not auto-scope to the calling `Parent`'s family.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. A non-integer `limit` or `offset`, or a value outside these bounds, is rejected with `ERR_INVALID_REQUEST`; an empty-string value for either is treated as absent (the default applies). Unless an endpoint states otherwise, list results are ordered by `created_at` ascending. Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Logical Clock

Every resource carries a server-minted `id` formatted as a UUID with no type prefix; clients never supply it. Most resources additionally carry three system-managed fields: `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and `version`, an integer that begins at 1 and increments by one on every mutation. The `updated_at` field is refreshed on any change to the resource. One entity is the exception: an `Attendance` record is append-only and carries only `id` and `created_at` — it has neither an `updated_at` nor a `version` field. (Attendance is "corrected" not by mutation in place but by writing a new `result`; see §3.6.)

The system runs on a **logical clock** rather than wall-clock time. On server startup the clock reads exactly `2026-01-01T00:00:00Z`; before any clock-setting call it holds this default and never falls back to real time. A `StudioAdmin` may advance the clock to a supplied UTC instant via the `to_iso8601` field. Advancing the clock is consequential: it is the trigger that flips overdue invoices to past-due (see §3.9) and governs both the costume rush window and recital completion eligibility. Every rule that reads "the clock" in this document means this logical clock.

### 2.5. Monetary Values and Rounding

All money in the system is stored and exchanged as **integer cents**; there are no fractional-cent values in storage or in responses. Most monetary computations — invoice totals, costume prices, ticket prices, travel charges, credit application — are exact integer arithmetic and require no rounding. The one place rounding occurs is the tuition discount calculation (§3.3), where percentage discounts are applied to a per-line base. Wherever a percentage is applied, the result is **rounded half up** to a whole cent at the moment specified, and the pinned rounding order described in §3.3 must be followed exactly. A family's wallet balance, held in `account_credit_cents`, is never permitted to go negative.

### 2.6. Hierarchical Consistency and Cascading Reconciliation

Many operations mutate more than one entity, and the system reconciles all of them within the same request. When a parent resource transitions in a way that invalidates its children, the children are resolved in the same operation; when a child mutates in a way that changes a parent's derived count or status, the parent is updated to match. A confirmed enrollment increments its section's `enrolled_count`; a drop decrements it; a held seat increments a recital's `seats_sold`; a rostered membership increments a team's `roster_count`. Each such derived count drives a status the parent then re-evaluates (a section reaching capacity, a recital selling out, and so on). Every reconciliation that mutates a resource refreshes that resource's `updated_at` and increments its `version` — including the system-driven transitions a client did not request directly, such as a section flipping to `FULL` or a recital flipping to `SOLD_OUT`. Discount tiers, waitlist ranks, and family statuses are likewise recomputed in the same request that disturbs them; the specific recompute rules live in the workflow subsections of §3.

### 2.7. Nested Resource Retrieval and Existence Ordering

Many paths name a parent before a child — a section's sessions, a term's recitals, a team's memberships, a family's students. For any such request, the system validates the identifiers left to right and rejects the first one that does not resolve to a live resource with `ERR_NOT_FOUND`. A request for the sessions of a non-existent section fails on the section before the system considers the session. Existence (priority 4) is checked after authentication, role permission, and parent-ownership (priorities 1 through 3) but before any state or business rule. This ordering holds uniformly for reads, creates, and state transitions.

### 2.8. Optimistic Concurrency Control on Inventory Writes

Two operations contend for a fixed pool of slots and are therefore guarded by optimistic concurrency control: holding a recital seat and rostering a team membership. Each requires the client to echo the parent's last-observed `version` so the server can detect that the pool has moved underneath it.

A seat-hold request against a recital must carry `expected_recital_version`, and that value must equal the target `Recital`'s current `version`. If another writer has held a seat since the client last read the recital — legitimately advancing the recital toward `SOLD_OUT` and bumping its `version` — the client's view of remaining inventory is stale, and the hold is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful hold increments the recital's `version` by one, so each hold observes a fresh version.

Likewise, a team-membership add must carry `expected_team_version`, which must equal the target `CompetitionTeam`'s current `version`. If another writer has rostered a student since the client last read the team — filling a slot and bumping the team's `version` — the add is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful roster add increments the team's `version` by one. Both `expected_recital_version` and `expected_team_version` are required, non-optional inputs on their respective writes; no other endpoint takes a version field, and endpoints not named here perform no OCC check.

### 2.9. Family Fiscal Standing

A `Family` is the billing aggregate. It tracks `account_credit_cents` (a wallet balance increased by refunds and admin credits, decreased when applied to invoices, and never negative), `autopay_enabled` (whether tuition invoices auto-charge on the due date), and `payment_method_on_file` (true once a card has been attached). A family also carries `sibling_count` — the number of its `ACTIVE` students that hold at least one billing-active enrollment — which drives the family multi-student discount tier described in §3.3.

A family's `status` is either `ACTIVE` or `DELINQUENT`. It begins `ACTIVE`. It becomes `DELINQUENT` the moment any of its invoices goes past-due, and it returns to `ACTIVE` once the last past-due invoice is settled. Delinquency is a gate, not merely a label: while a family is `DELINQUENT`, it cannot confirm new enrollments and cannot sign students up for trips (see §3.2 and §3.7). Enabling auto-pay and paying an invoice both require a payment method to be on file; without one, those operations are refused with `ERR_NO_PAYMENT_METHOD`.

### 2.10. Validation Ordering

When several checks could reject a single request, they are evaluated in a fixed priority order, and the first to fail determines the error returned. Authentication comes first (`ERR_UNAUTHENTICATED`), then role permission (`ERR_FORBIDDEN_ROLE`), then parent-resource ownership for `Parent` actions (`ERR_NOT_RESOURCE_OWNER`), then existence of every referenced id (`ERR_NOT_FOUND`), then the legality of the requested state transition (`ERR_INVALID_STATE`), then optimistic-concurrency version match on guarded writes (`ERR_STALE_VERSION`). Only after those gates pass does the system evaluate domain-specific business rules — eligibility, capacity, scheduling conflicts, fiscal standing, and the like — and finally generic request well-formedness (`ERR_INVALID_REQUEST`) for malformed bodies, out-of-range enums, and violated numeric bounds. Where a workflow names several business checks, the relative ordering among them is stated in that workflow's subsection.

## 3. Business Logic & Workflows

### 3.1. Households, Students, and the Studio Configuration Spine

A household enters the system as a `Family`, created with an `email` and a `family_name`. The `email` is the parent account's login and must be unique across families, compared case-insensitively, and non-empty; a duplicate (case-insensitive) email is rejected with `ERR_INVALID_REQUEST`. A new family starts `ACTIVE` with `account_credit_cents` of zero, `payment_method_on_file` false, and `autopay_enabled` false. Self-registration is the one capability an `Anonymous` visitor has; a `StudioAdmin` may also create families. Attaching a payment method (via a `card_token`) flips `payment_method_on_file` to true. A `StudioAdmin` may grant goodwill credit by an `amount_cents` (a non-negative integer; a negative value is rejected with `ERR_INVALID_REQUEST`), which is added to the family's `account_credit_cents`. A family's `family_name` and `autopay_enabled` may be patched; turning `autopay_enabled` on is refused with `ERR_NO_PAYMENT_METHOD` unless a method is already on file. The patch endpoint also accepts an optional `expected_family_version`; when it is supplied and does not equal the family's current `version`, the patch is rejected with `ERR_STALE_VERSION` (HTTP 412), and when it is omitted no version check is performed. A patch that supplies no changed fields leaves the family's `version` and `updated_at` untouched (the resource is touched only when at least one field actually changes).

Each `Student` belongs to a family by `family_id` and is created with a `full_name`, a `birth_date` (an ISO 8601 date), and a `level`. The level is one of `PETITE`, `NOVICE`, `INTERMEDIATE`, `ADVANCED`, or `ELITE`, treated as an ordinal ladder in that order for placement and rostering. A student begins `ACTIVE`. A parent (or admin) may withdraw a student, moving its `status` to `WITHDRAWN`; the cascade is described in §3.4. The student also carries a derived `age_as_of_cutoff`, a whole-year age computed against a term (see §3.2).

The scheduling spine is configured by a `StudioAdmin`. A `Term` is created with a `name`, a `start_date`, an `end_date` that must be strictly after the start, an `age_cutoff_date` that must fall on or within the term's start and end dates inclusive, and a `monthly_billing_day` — the day of month (an integer from 1 through 28) on which tuition invoices are dated. A term begins `DRAFT`, where configuration is allowed; it is opened to `OPEN` (enrollment and billing allowed) and later frozen to `CLOSED`. A `Room` is created with a `name`, a `capacity` of at least one student, and a `turnover_buffer_minutes` (defaulting to 0, never negative) — the cleaning gap that must separate consecutive sessions in that room. An `Instructor` is created with a `full_name`, a unique case-insensitive `email` (a duplicate is rejected with `ERR_INVALID_REQUEST`), and a `max_weekly_sessions` cap defaulting to 30 (at least one) on the total number of sessions the instructor may be assigned across all sections.

### 3.2. Sections, Sessions, and the Scheduling Constraints

A `ClassSection` is the unit of instruction, created under a term with its `term_id`, the `room_id` whose weekly sessions it occupies, the assigned `instructor_id`, a `discipline` (one of `BALLET`, `JAZZ`, `TAP`, `HIPHOP`, `CONTEMPORARY`, or `ACRO`), a `required_level`, an inclusive `min_age` and `max_age` placement band (each a non-negative integer, with `max_age` at least `min_age`), the `monthly_tuition_cents` base price for one student before discounts, and a `capacity_cap`. The section's effective capacity is the smaller of its `capacity_cap` and its room's `capacity`. A section's derived `enrolled_count` is the number of its enrollments in `CONFIRMED` or `WAITLIST_PROMOTED` placement, and this count drives both capacity gating and waitlist promotion.

A section walks a branching lifecycle through `PLANNED`, `SCHEDULED`, `OPEN`, `FULL`, and the terminal `CANCELLED`. It is `PLANNED` at creation. Adding the first `ClassSession` moves it to `SCHEDULED`. When its parent term opens, a `SCHEDULED` section transitions to `OPEN` and becomes enrollable — this is a system transition guarded on the term: a section opens only because its term opened, never independently. While `OPEN`, the section accepts confirmations until its `enrolled_count` reaches effective capacity, at which point the system flips it to `FULL` and routes further placements to the waitlist. Should a confirmed enrollment later drop while no waitlisted enrollment is promoted to refill the slot, the section returns from `FULL` to `OPEN`, and the next placement may confirm; this `OPEN` ↔ `FULL` cycle tracks `enrolled_count` crossing the cap.

A `ClassSession` is a recurring weekly slot under a section's `section_id`, defined by a `day_of_week` (an integer 0 for Monday through 6 for Sunday), a `start_minute` (minutes since midnight, 0 through 1439), and an `end_minute` (minutes since midnight, in the inclusive range 1 through 1440, strictly greater than `start_minute`, with no midnight wrap). Adding a session enforces two scheduling constraints in addition to the generic transition and existence checks. First, the room must be free: a new session **room-conflicts** if, on the same `day_of_week` and in the same room, its window from its start up to its end *plus the room's `turnover_buffer_minutes`* overlaps the equivalently-buffered window of any other section's session in that room — a violation is rejected with `ERR_ROOM_CONFLICT`. Second, the instructor must be free: a new session **instructor-conflicts** if, on the same `day_of_week`, its plain start-to-end window (no buffer) overlaps another session of the same instructor, rejected with `ERR_INSTRUCTOR_CONFLICT`. Finally, the assignment must not push the instructor's total session count across all sections above their `max_weekly_sessions`, which is rejected with `ERR_INSTRUCTOR_OVERLOADED`. Among these three, the room conflict is evaluated first, then the instructor time conflict, then the instructor weekly-cap.

A `StudioAdmin` may cancel a section. Cancellation is permitted from `PLANNED`, `SCHEDULED`, or `OPEN`, and `CANCELLED` is terminal; a cancel from a `PLANNED` section requires that the section have no confirmed enrollments. When a populated section is cancelled, every enrollment in `CONFIRMED`, `WAITLISTED`, or `WAITLIST_PROMOTED` placement is moved to `DROPPED`; each one that was in `CONFIRMED` or `WAITLIST_PROMOTED` also has its `billing_status` moved to `BILLING_ENDED`. As a further cascade, each dropped, formerly-confirmed enrollment's `monthly_charge_cents` is removed from any draft fee on its family's open invoice and the family's remaining billing-active enrollments have their `monthly_charge_cents` recomputed, since losing a class can shift the family's discount tier.

Opening a term is itself a guarded `StudioAdmin` action: a term may move from `DRAFT` to `OPEN` only if it has at least one section in `SCHEDULED` status and its `age_cutoff_date` lies within its date window; on success every `SCHEDULED` section under it transitions to `OPEN`. Closing a term moves it from `OPEN` to the terminal `CLOSED`, and is permitted only when every invoice for that term is already `PAID` or `VOID`. Closing ends billing without cancelling sections: every enrollment under the term whose `billing_status` is `BILLING_ACTIVE` moves to `BILLING_ENDED`, while sections are left in whatever status they currently hold.

### 3.3. Placement, Enrollment, and the Tuition Discount Engine

Placing a student into a section creates an `Enrollment`, the junction that ties a student to a class. It is created with a `student_id` and a `section_id`, optionally citing a `makeup_for_attendance_id` for a makeup placement (see §3.6); the `makeup_for_attendance_id` field is present in the enrollment object only when a makeup attendance was actually cited, and is absent entirely on ordinary enrollments. The enrollment's `family_id` is copied from the student at creation for billing rollup. An enrollment carries two independent status dimensions. Its `placement_status` runs through `PENDING`, `CONFIRMED`, `WAITLISTED`, `WAITLIST_PROMOTED`, and the terminal `DROPPED`. Its `billing_status` runs through `UNBILLED`, `BILLING_ACTIVE`, `BILLING_PAUSED`, and `BILLING_ENDED`, and turns independently of placement. It also carries a `waitlist_rank` and a derived `monthly_charge_cents`.

Creating an enrollment auto-resolves placement. If the section is `OPEN` with room under effective capacity and the student is eligible, the enrollment is confirmed directly; if the section is `FULL`, the enrollment is waitlisted; eligibility is required in both cases. A section in any other status (`PLANNED`, `SCHEDULED`, or `CANCELLED`), or an `OPEN` section already at effective capacity, is not an enrollable target, and the create is rejected with `ERR_INVALID_STATE`; on the create path this enrollable-state resolution is evaluated only after the makeup citation check (if any) and the level/age eligibility checks have passed, and the family-delinquency check applies only on the `OPEN`-with-room (confirming) branch. (The enrollment record is minted with `placement_status` `PENDING`, `billing_status` `UNBILLED`, `waitlist_rank` `0`, and `monthly_charge_cents` `0` before this resolution runs.) Eligibility has two cross-entity conditions. The student's `level` must be at least the section's `required_level` on the ordinal ladder — a level below the requirement is rejected with `ERR_LEVEL_TOO_LOW`. And the student's `age_as_of_cutoff` must fall within the section's inclusive `min_age`-to-`max_age` band — an age below `min_age` or above `max_age` is rejected with `ERR_AGE_OUT_OF_BAND`. A confirmation additionally requires that the family not be `DELINQUENT`; a delinquent family's confirmation is refused with `ERR_FAMILY_DELINQUENT`. The level check is evaluated before the age check.

A student's `age_as_of_cutoff` is computed as whole years, floored, against the relevant term's `age_cutoff_date`. Take the difference between the cutoff year and the student's `birth_date` year; then, if the cutoff's month-and-day falls earlier in the calendar year than the student's birth month-and-day, subtract one. The result is the student's age in completed years as of the cutoff, and it is what the age band is checked against. Because a freshly created student is not yet tied to any term, its stored `age_as_of_cutoff` is initialized to `0` at creation and is first computed for real — and thereafter recomputed and persisted on the student — whenever placement is evaluated against a term (i.e. on enrollment create and on an explicit admin confirm).

Confirming an enrollment — whether through the auto-resolve path at creation or through an explicit admin confirm of a `PENDING` enrollment — moves `placement_status` to `CONFIRMED`, increments the section's `enrolled_count` by one, moves `billing_status` from `UNBILLED` to `BILLING_ACTIVE`, and runs the tuition recompute (below). If that confirmation brings `enrolled_count` to effective capacity, the section flips from `OPEN` to `FULL`. The explicit admin confirm path requires the enrollment to be `PENDING` and its section to be `OPEN` or `FULL` (otherwise `ERR_INVALID_STATE`), re-runs the level/age eligibility checks, and has one extra guard the auto-resolve path does not: confirming when the section is already at effective capacity is rejected with `ERR_CAPACITY_EXCEEDED`; this capacity guard is evaluated after the eligibility checks and before the family-delinquency check. (On the creation path, a full section instead produces a waitlisted enrollment rather than this error.) When an enrollment is waitlisted, its `placement_status` becomes `WAITLISTED`, its `waitlist_rank` is assigned as one more than the count of enrollments already `WAITLISTED` for that section, ordered by `created_at` ascending, and its `billing_status` stays `UNBILLED`.

**The tuition discount engine** recomputes the `monthly_charge_cents` of every billing-active enrollment in a family whenever that family's enrollment profile changes — on a confirm, on a waitlist promotion, on a drop, and on a billing pause or resume. Only enrollments with `billing_status` equal to `BILLING_ACTIVE` participate. For ordering, those active enrollments are sorted by their section's `monthly_tuition_cents` descending, breaking ties by `created_at` ascending (never by `id`). Two discounts then stack.

The **multi-class discount** applies per student, by the index of the class within that student's own billing-active enrollments (ordered by section tuition descending, then `created_at` ascending, so the highest-priced class is always the first and never discounted). A student's first class gets no discount; the second class is discounted by ten percent; the third and any further class are discounted by twenty percent. The **family multi-student discount** then applies on top, keyed to the family's `sibling_count` (the count of `ACTIVE` students who hold at least one billing-active enrollment): one such student yields no family discount, two students yield a five percent discount, and three or more students yield an eight percent discount.

The per-enrollment charge is computed with a **pinned rounding order**: start from the section's `monthly_tuition_cents` as the base; apply the multi-class percentage and round that intermediate result half up to a whole cent; then apply the family percentage to that rounded figure and round half up again to a whole cent. The twice-rounded result is the enrollment's `monthly_charge_cents`. Rounding happens per line item at each of the two stages — the family percentage is never folded into the multi-class percentage, and totals are never summed before rounding. This live, per-enrollment `monthly_charge_cents` reflects the family's current billing-active set at any instant and shifts as siblings and classes are added or dropped; it is the provisional figure. The invoiced figure is a frozen snapshot: at invoice generation the then-current `monthly_charge_cents` of each billing-active enrollment is summed, and a later drop does not retroactively alter an already-generated invoice.

A `StudioAdmin` may pause and resume billing on a `CONFIRMED` enrollment without touching its placement. Pausing requires the enrollment to be `BILLING_ACTIVE` and moves `billing_status` to `BILLING_PAUSED`; resuming requires `BILLING_PAUSED` and returns it to `BILLING_ACTIVE`. Either toggle re-runs the family tuition recompute, because a paused enrollment leaves the active set (lowering counts and possibly the discount tier) and a resumed one rejoins it. Throughout, the enrollment's `placement_status` remains `CONFIRMED`.

### 3.4. Dropping, Waitlist Promotion, and Withdrawal Cascades

A parent (or admin) may drop a confirmed enrollment. Dropping requires the enrollment to be `CONFIRMED` and, for a `Parent`, that they own the student. The drop moves `placement_status` to `DROPPED`, decrements the section's `enrolled_count` by one, and moves `billing_status` from `BILLING_ACTIVE` to `BILLING_ENDED`. The family's remaining billing-active enrollments then recompute their `monthly_charge_cents` — and because fewer classes can raise the discount tier, charges may move. The drop then attempts a waitlist promotion: if any `WAITLISTED` enrollment exists for that section, the one with the lowest `waitlist_rank` (the earliest `created_at`) is promoted; if none is eligible, the section returns from `FULL` to `OPEN`.

Promotion is a system transition with its own cascade. The promoted enrollment moves from `WAITLISTED` to `WAITLIST_PROMOTED`, the section's `enrolled_count` increments by one, the enrollment's `billing_status` moves from `UNBILLED` to `BILLING_ACTIVE`, the tuition engine recomputes that enrollment and the rest of its family's billing-active enrollments, and every still-`WAITLISTED` enrollment behind it has its `waitlist_rank` decremented by one to close the gap. A `WAITLIST_PROMOTED` enrollment may itself later be dropped (decrementing `enrolled_count`, ending billing, recomputing family tuition, and promoting the next waitlisted enrollment if one exists). A purely `WAITLISTED` enrollment may also be dropped; that simply moves it to `DROPPED` and resequences the remaining waitlist ranks, with no capacity or billing effect since it never held a confirmed slot.

Withdrawing a student is the household-level counterpart. A withdrawal requires the student to be `ACTIVE` and moves its `status` to `WITHDRAWN`. Every one of that student's enrollments in `CONFIRMED` or `WAITLIST_PROMOTED` is dropped (placement to `DROPPED`, billing to `BILLING_ENDED`, with the same capacity, waitlist-promotion, and tuition cascades a normal drop triggers), and every purely `WAITLISTED` enrollment of that student is moved to `DROPPED`. The family's `sibling_count` is then recomputed, and the family's remaining billing-active enrollments recompute their `monthly_charge_cents`.

### 3.5. Attendance and Makeups

An `Instructor` (or `StudioAdmin`) marks attendance for a session occurrence of an enrollment. An `Attendance` record cites the `enrollment_id` it covers and the `session_id` (the weekly slot) being marked, records the calendar `occurred_on` date of the occurrence, and a `result` of `PRESENT`, `ABSENT_EXCUSED`, or `ABSENT_UNEXCUSED`. The `occurred_on` date must fall on the session's `day_of_week` and inside the section's term window. Attendance is append-only and has no `version`; a correction is made by amending it, which writes a new `result` value rather than editing the old record in place.

Two derived flags govern makeups. An attendance row's `makeup_eligible` is true only when its `result` is `ABSENT_EXCUSED` and no makeup has yet been consumed against it; amending the `result` recomputes this flag. Its `makeup_consumed` becomes true once a makeup enrollment has been booked citing it through `makeup_for_attendance_id`. A makeup placement is an enrollment that cites such an attendance: it is allowed only when the cited attendance is `makeup_eligible` (that is, `ABSENT_EXCUSED` and not yet consumed) and the attendance's `occurred_on` falls within the makeup window — the number of days defined by `MAKEUP_WINDOW_DAYS`, which is `30`, immediately preceding the makeup session's date, where the makeup session's date is taken to be the current logical-clock date at the moment the makeup enrollment is created. Concretely, with `D` the logical-clock date, the cited `occurred_on` must satisfy `D − MAKEUP_WINDOW_DAYS ≤ occurred_on ≤ D` (both bounds inclusive). A citation that fails either condition is rejected with `ERR_MAKEUP_INELIGIBLE`. When a makeup enrollment is successfully created citing an attendance, that attendance's `makeup_consumed` flips to true and its `makeup_eligible` flips to false; eligibility and window are validated before the placement's eligibility (level/age) checks.

### 3.6. Costume Sizing and Ordering

A `StudioAdmin` creates a `Costume` for a section under its `section_id`, with a `name`, a `unit_price_cents` base price, a `size_window_close_date` after which sizing locks and orders incur a surcharge, and a `rush_surcharge_cents` flat surcharge (defaulting to 0, never negative). A costume begins `SIZING_OPEN` and moves to `ORDERED` once its orders are submitted. Whether the rush surcharge applies is governed purely by the logical clock against `size_window_close_date`, not by this status.

A parent (or admin) places a `CostumeOrder` citing the `costume_id`, the `enrollment_id` of the enrolled student it is for, and a `size_code` of `CHILD_S`, `CHILD_M`, `CHILD_L`, `ADULT_S`, `ADULT_M`, or `ADULT_L`. The cited enrollment must be `CONFIRMED` or `WAITLIST_PROMOTED` in the costume's own section, or the order is rejected with `ERR_NOT_ENROLLED_IN_SECTION`. The order begins as a `DRAFT` and its `price_cents` is pinned only when submitted.

Submitting a costume's orders is a `StudioAdmin` action that submits every `DRAFT` order for that costume at once, processing them in `created_at` order. The costume must be `SIZING_OPEN`, and each order's cited enrollment must still be `CONFIRMED` or `WAITLIST_PROMOTED`; this enrollment-status condition is validated across all draft orders before any of them is pinned or submitted, so a single offending order rejects the whole batch with `ERR_NOT_ENROLLED_IN_SECTION` and leaves every order a `DRAFT` and the costume `SIZING_OPEN`. For each order, `price_cents` is pinned by the **costume price rule**: if the clock's date is strictly after the costume's `size_window_close_date`, the price is `unit_price_cents` plus `rush_surcharge_cents`; otherwise it is just `unit_price_cents`. The boundary is strict — on the close date itself there is no surcharge; only a clock date past it triggers the rush price. Each submitted order moves from `DRAFT` to `SUBMITTED`, its pinned `price_cents` is folded as a fee line into its family's current open invoice (the invoice's `fees_cents` increases by that amount and its amount due is recomputed), and the costume moves to `ORDERED`. Submitting a costume that has no `DRAFT` orders is still permitted: nothing is priced or folded, but the costume nonetheless moves to `ORDERED`. The family's "current open invoice" is its most recently created invoice still in `OPEN` status (ties on `created_at` broken by creation order); if the family has no `OPEN` invoice, the fee is simply not folded anywhere — it lands on no invoice and produces no account credit.

A costume order may be cancelled. A `DRAFT` order (cancellable by its parent or an admin) simply becomes `CANCELLED` with no charge, since none had been applied. A `SUBMITTED` order (cancellable by a `StudioAdmin`) becomes `CANCELLED` with compensation: its `price_cents` is removed from the family's current open invoice fees if such an invoice exists, or, if the family currently has no `OPEN` invoice, credited to the family's `account_credit_cents` instead. The conserved quantity — invoice fees plus family credit — returns to its pre-order value.

### 3.7. Competition Teams, Rosters, and Travel

A `StudioAdmin` forms a `CompetitionTeam` with a `name`, a `min_level` on the ordinal level ladder, and a `roster_cap`. A team begins `FORMING`, where roster changes are allowed, and may be locked to `LOCKED`, which freezes the roster. The team's derived `roster_count` is the number of its memberships in `ROSTERED` status.

Rostering a student creates a `TeamMembership` whose `team_id` is the rostering team, citing the `student_id`, and is OCC-guarded (see §2.8) on `expected_team_version`. Memberships may be listed filtered by `team_id` or by `student_id`. Beyond the version check, the add must not push `roster_count` above the team's `roster_cap`, and the student's `level` must be at least the team's `min_level`; either violation is rejected with `ERR_ROSTER_FULL`. A successful add sets the membership `ROSTERED`, increments `roster_count`, and increments the team's `version`. A membership may be released by a `StudioAdmin` while the team is still `FORMING`, moving it from `ROSTERED` to the terminal `RELEASED` and decrementing `roster_count`. Once a team is `LOCKED`, further membership adds and releases are rejected with `ERR_INVALID_STATE`.

A team may propose a `TravelTrip` with a `destination`, a `depart_date`, a `return_date` no earlier than departure, a `per_member_cost_cents` charged to each participating family, a `chaperone_ratio` (the required minimum students per chaperone, at least one), and a `chaperone_count` of registered chaperones (defaulting to 0, never negative). A trip begins `PROPOSED`, where signups are allowed. A rostered membership signs up via a `TripParticipant` whose `trip_id` is the trip, citing the `membership_id`; the membership must be `ROSTERED` on the trip's team, and the participant's `family_id` is copied from the membership's student's family for travel billing. Participants may be listed filtered by `trip_id`, `family_id`, or `membership_id`. A participant begins `GOING`. Signing up is gated by family fiscal standing: a `DELINQUENT` family cannot add a participant, and the attempt is refused with `ERR_FAMILY_DELINQUENT`. The trip's derived `participant_count` is the number of its participants in `GOING` status.

Confirming a trip is a `StudioAdmin` action permitted only from `PROPOSED`. It requires that the parent team be `LOCKED`, that `participant_count` be at least one, and that the trip satisfy the **chaperone requirement**: the number of chaperones required is the `participant_count` divided by the `chaperone_ratio` and rounded up to the next whole number, and this required count must be at most the `chaperone_count`. A participant count exactly divisible by the ratio needs exactly that quotient; one participant over a multiple bumps the requirement up by one. Failing this is rejected with `ERR_INSUFFICIENT_CHAPERONES`. On confirmation the trip moves to `CONFIRMED` and each `GOING` participant's `per_member_cost_cents` is added as a fee line to that participant's family's open invoice — a cascade that can touch many families at once.

A participant may withdraw, moving from `GOING` to the terminal `WITHDRAWN` and decrementing the trip's `participant_count`. If the trip is already `CONFIRMED`, withdrawing compensates: the `per_member_cost_cents` is removed from the family's open invoice fees, or credited to the family's `account_credit_cents` if there is no open invoice, conserving the travel money. Cancelling a trip is a `StudioAdmin` action. Cancelling a `PROPOSED` trip moves every participant to `WITHDRAWN` with no charges to reverse. Cancelling a `CONFIRMED` trip likewise withdraws every `GOING` participant but compensates each one — refunding `per_member_cost_cents` to the family's open invoice fees or `account_credit_cents` — so the total travel money is conserved. The trip ends in the terminal `CANCELLED`.

### 3.8. Recitals, Seats, and the Ticket Allotment

A `StudioAdmin` announces a `Recital` under a term with its `term_id`, a `name`, a `show_datetime`, a `total_seats` count (at least one), a `ticket_price_cents`, and a `free_tickets_per_family` complimentary allowance (defaulting to 0, never negative) that each family receives across all its students before paid pricing begins. A recital begins `ANNOUNCED`. Its derived `seats_sold` counts its seat assignments in `HELD` or `PURCHASED` status, and its `status` is a compound value derived from that count: opening sales moves it to `ON_SALE` (allowed only when the parent term is `OPEN` and `total_seats` is at least one); when `seats_sold` reaches `total_seats` the system flips it to `SOLD_OUT`; and when a held or purchased seat is released so that `seats_sold` falls back below `total_seats`, it returns to `ON_SALE`. This `ON_SALE` ↔ `SOLD_OUT` cycle tracks `seats_sold` against `total_seats`.

Holding a seat creates a `SeatAssignment` whose `recital_id` is the recital it belongs to, citing the `family_id` holding it and a `seat_label`, and is OCC-guarded (see §2.8) on `expected_recital_version`. Seats may be listed across recitals filtered by `recital_id`. The `seat_label` must be unique within the recital among seats not in `RELEASED` status; a duplicate label, or a hold that would push `seats_sold` past `total_seats`, is rejected with `ERR_RECITAL_SOLD_OUT`. Holding is permitted only while the recital is `ON_SALE` or `SOLD_OUT` (a hold against an `ANNOUNCED` or `COMPLETED` recital is rejected with `ERR_INVALID_STATE`); this enrollable-state check precedes the optimistic-concurrency version match, which in turn precedes the duplicate-label and sold-out gates. A seat begins `HELD`. Its price and complimentary flag are pinned at hold time by the **ticket allotment rule**: count the holding family's seats already in `HELD` or `PURCHASED` status for this recital; if that count is below the recital's `free_tickets_per_family`, the seat's `is_complimentary` is true and its `price_cents` is 0, otherwise `is_complimentary` is false and `price_cents` is the recital's `ticket_price_cents`. The allotment is a waterfall: the earliest of a family's held-or-purchased seats, in `created_at` order, fill the free allowance first and later seats are paid. A successful hold increments `seats_sold` by one and the recital's `version` by one, and may flip the recital to `SOLD_OUT`.

A held seat may be purchased by the holding family (or an admin), moving it from `HELD` to `PURCHASED`; this is permitted only while its recital is `ON_SALE` or `SOLD_OUT` (otherwise rejected with `ERR_INVALID_STATE`). The pinned `price_cents` is charged, folded into the family's current open invoice fees if one exists, and a complimentary seat charges nothing. Purchasing does not advance the recital's `version`. A held seat may be released by the holding family back to inventory, moving it to the terminal `RELEASED`, decrementing the recital's `seats_sold`, returning a `SOLD_OUT` recital to `ON_SALE`, and recomputing the family's complimentary allotment for the freed slot. A purchased seat may be released by a `StudioAdmin`: this decrements `seats_sold`, refunds the seat's `price_cents` to the family's `account_credit_cents`, and returns a `SOLD_OUT` recital to `ON_SALE` — the seat inventory and the family's paid-plus-credit balance both reconcile to their pre-purchase totals.

Completing a recital is a `StudioAdmin` action permitted from `ON_SALE` or `SOLD_OUT` only once the clock has reached or passed the `show_datetime`. On completion every `HELD` seat is released while `PURCHASED` seats are retained, and the recital moves to the terminal `COMPLETED`.

### 3.9. Invoicing, Payment, Auto-Pay, and Delinquency

A `StudioAdmin` generates an `Invoice` for a `family_id`, a `term_id`, and a `billing_month` formatted as `YYYY-MM`. At most one non-`VOID` invoice may exist per family, term, and billing month; a duplicate is rejected with `ERR_DUPLICATE_INVOICE`. Generation computes the invoice totals as a **waterfall**, in a pinned evaluation order. First, `tuition_cents` is the sum of the current `monthly_charge_cents` across the family's enrollments whose `billing_status` is `BILLING_ACTIVE` at generation time and whose section belongs to the invoice's `term_id` — a frozen snapshot. Next, `fees_cents` is the sum of the fee lines (costume, travel, and ticket charges) folded into this invoice; at generation it begins at `0`, and fee lines are folded in only afterward as costume, travel, and ticket charges land on this — the family's current open invoice. The gross is `tuition_cents` plus `fees_cents`. Then the family wallet is applied as a credit waterfall: `credit_applied_cents` is the smaller of the family's `account_credit_cents` and that gross, and the family's `account_credit_cents` is decremented by the amount applied at generation. Finally, `amount_due_cents` is the gross minus the applied credit, floored at zero so it is never negative. The invoice begins `OPEN`.

An invoice runs through `OPEN`, `PAID`, `PAST_DUE`, and the terminal `VOID`. Paying an `OPEN` or `PAST_DUE` invoice requires the family to have a payment method on file (otherwise `ERR_NO_PAYMENT_METHOD`); on success the `amount_due_cents` is charged and the invoice moves to `PAID`. Payment may be a manual parent action or the system's auto-pay on the billing day for families with `autopay_enabled`. When an invoice is paid, if the family was `DELINQUENT` and no other `PAST_DUE` invoice remains for it, the family returns to `ACTIVE`.

Past-due status is clock-driven. When the logical clock is advanced past the due day of an `OPEN` invoice's `billing_month` (the term's `monthly_billing_day` within that month) while the invoice is still `OPEN`, the invoice flips to `PAST_DUE` and its family's `status` flips to `DELINQUENT` — which in turn gates that family's new enrollment confirmations and trip signups, as described in §2.9. A `StudioAdmin` may void an `OPEN` or `PAST_DUE` invoice, moving it to the terminal `VOID`; any `credit_applied_cents` that had been drawn from the wallet at generation is returned to the family's `account_credit_cents`, conserving the credit balance. If the invoice being voided was `PAST_DUE` and no other `PAST_DUE` invoice remains for that family, the family's `status` returns to `ACTIVE`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource or add a new resource to a collection return `201 Created`. Operations that modify or transition an existing resource — including state-changing actions and list/fetch reads — return `200 OK`. Reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock to a UTC instant | StudioAdmin |
| POST | `/families` | Register a family/parent account | Anonymous, StudioAdmin |
| GET | `/families/{id}` | Fetch a family | StudioAdmin, Parent |
| GET | `/families` | List families | StudioAdmin |
| PATCH | `/families/{id}` | Update family fields; toggle auto-pay | StudioAdmin, Parent |
| POST | `/families/{id}/payment-method` | Attach a payment method | StudioAdmin, Parent |
| POST | `/families/{id}/credit` | Grant account credit | StudioAdmin |
| POST | `/families/{id}/students` | Add a student to a family | StudioAdmin, Parent |
| GET | `/families/{id}/students` | List a family's students | StudioAdmin, Parent |
| GET | `/students/{id}` | Fetch a student | StudioAdmin, Parent, Instructor |
| POST | `/students/{id}/withdraw` | Withdraw a student | StudioAdmin, Parent |
| POST | `/terms` | Create a term | StudioAdmin |
| GET | `/terms/{id}` | Fetch a term | StudioAdmin, Parent, Instructor |
| POST | `/terms/{id}/open` | Open a term for enrollment | StudioAdmin |
| POST | `/terms/{id}/close` | Close a term | StudioAdmin |
| POST | `/rooms` | Create a room | StudioAdmin |
| GET | `/rooms/{id}` | Fetch a room | StudioAdmin, Instructor |
| POST | `/instructors` | Create an instructor | StudioAdmin |
| GET | `/instructors/{id}` | Fetch an instructor | StudioAdmin, Instructor |
| POST | `/sections` | Create a class section | StudioAdmin |
| GET | `/sections/{id}` | Fetch a section | StudioAdmin, Parent, Instructor |
| GET | `/sections` | List sections (filter by term_id, room_id, instructor_id) | StudioAdmin, Parent, Instructor |
| POST | `/sections/{id}/sessions` | Add a weekly session to a section | StudioAdmin |
| GET | `/sections/{id}/sessions` | List a section's sessions | StudioAdmin, Parent, Instructor |
| POST | `/sections/{id}/cancel` | Cancel a section | StudioAdmin |
| GET | `/sessions/{id}` | Fetch a session | StudioAdmin, Parent, Instructor |
| POST | `/enrollments` | Place a student into a section | StudioAdmin, Parent |
| GET | `/enrollments/{id}` | Fetch an enrollment | StudioAdmin, Parent, Instructor |
| GET | `/enrollments` | List enrollments (filter by section_id, student_id, family_id) | StudioAdmin, Parent, Instructor |
| POST | `/enrollments/{id}/confirm` | Explicitly confirm a pending enrollment | StudioAdmin |
| POST | `/enrollments/{id}/drop` | Drop an enrollment | StudioAdmin, Parent |
| POST | `/enrollments/{id}/pause-billing` | Pause billing on a confirmed enrollment | StudioAdmin |
| POST | `/enrollments/{id}/resume-billing` | Resume billing on a paused enrollment | StudioAdmin |
| POST | `/enrollments/{id}/attendance` | Mark attendance for a session occurrence | StudioAdmin, Instructor |
| GET | `/enrollments/{id}/attendance` | List attendance for an enrollment | StudioAdmin, Instructor, Parent |
| GET | `/attendance/{id}` | Fetch an attendance record | StudioAdmin, Instructor, Parent |
| POST | `/attendance/{id}/amend` | Amend an attendance result | StudioAdmin, Instructor |
| GET | `/sessions/{id}/attendance` | List attendance for a session | StudioAdmin, Instructor |
| POST | `/sections/{id}/costumes` | Create a costume for a section | StudioAdmin |
| GET | `/sections/{id}/costumes` | List costumes for a section | StudioAdmin, Parent |
| GET | `/costumes/{id}` | Fetch a costume | StudioAdmin, Parent |
| POST | `/costumes/{id}/submit-order` | Submit all draft orders for a costume | StudioAdmin |
| POST | `/costume-orders` | Create a draft costume order | StudioAdmin, Parent |
| GET | `/costume-orders/{id}` | Fetch a costume order | StudioAdmin, Parent |
| GET | `/costume-orders` | List costume orders (filter by costume_id, enrollment_id) | StudioAdmin, Parent |
| POST | `/costume-orders/{id}/cancel` | Cancel a costume order | StudioAdmin, Parent |
| POST | `/terms/{id}/recitals` | Create a recital under a term | StudioAdmin |
| GET | `/terms/{id}/recitals` | List recitals for a term | StudioAdmin, Parent |
| GET | `/recitals/{id}` | Fetch a recital | StudioAdmin, Parent |
| POST | `/recitals/{id}/open-sales` | Open ticket sales | StudioAdmin |
| POST | `/recitals/{id}/complete` | Complete a recital | StudioAdmin |
| POST | `/recitals/{id}/seats` | Hold a seat for a family | StudioAdmin, Parent |
| GET | `/recitals/{id}/seats` | List seats for a recital (filter by family_id) | StudioAdmin, Parent |
| GET | `/seats/{id}` | Fetch a seat assignment | StudioAdmin, Parent |
| GET | `/seats` | List seat assignments (filter by family_id, recital_id) | StudioAdmin, Parent |
| POST | `/seats/{id}/purchase` | Purchase a held seat | StudioAdmin, Parent |
| POST | `/seats/{id}/release` | Release a held or purchased seat | StudioAdmin, Parent |
| POST | `/teams` | Create a competition team | StudioAdmin |
| GET | `/teams/{id}` | Fetch a team | StudioAdmin, Parent, Instructor |
| POST | `/teams/{id}/lock` | Lock a team roster | StudioAdmin |
| POST | `/teams/{id}/memberships` | Roster a student onto a team | StudioAdmin |
| GET | `/teams/{id}/memberships` | List a team's memberships | StudioAdmin, Parent |
| GET | `/memberships` | List memberships (filter by student_id, team_id) | StudioAdmin, Parent |
| GET | `/memberships/{id}` | Fetch a membership | StudioAdmin, Parent |
| POST | `/memberships/{id}/release` | Release a rostered membership | StudioAdmin |
| POST | `/teams/{id}/trips` | Propose a travel trip for a team | StudioAdmin |
| GET | `/teams/{id}/trips` | List a team's trips | StudioAdmin, Parent |
| GET | `/trips/{id}` | Fetch a trip | StudioAdmin, Parent |
| POST | `/trips/{id}/participants` | Sign a membership up for a trip | StudioAdmin, Parent |
| GET | `/trips/{id}/participants` | List a trip's participants | StudioAdmin, Parent |
| GET | `/participants` | List participants (filter by family_id, membership_id, trip_id) | StudioAdmin, Parent |
| GET | `/participants/{id}` | Fetch a trip participant | StudioAdmin, Parent |
| POST | `/participants/{id}/withdraw` | Withdraw a trip participant | StudioAdmin, Parent |
| POST | `/trips/{id}/confirm` | Confirm a trip | StudioAdmin |
| POST | `/trips/{id}/cancel` | Cancel a trip | StudioAdmin |
| POST | `/invoices/generate` | Generate a monthly tuition invoice | StudioAdmin |
| GET | `/invoices/{id}` | Fetch an invoice | StudioAdmin, Parent |
| GET | `/invoices` | List invoices (filter by family_id, term_id, status) | StudioAdmin, Parent |
| POST | `/invoices/{id}/pay` | Pay an open or past-due invoice | StudioAdmin, Parent |
| POST | `/invoices/{id}/void` | Void an open or past-due invoice | StudioAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_LEVEL_TOO_LOW` | 422 |
| `ERR_AGE_OUT_OF_BAND` | 422 |
| `ERR_ROOM_CONFLICT` | 409 |
| `ERR_INSTRUCTOR_CONFLICT` | 409 |
| `ERR_INSTRUCTOR_OVERLOADED` | 422 |
| `ERR_ROSTER_FULL` | 422 |
| `ERR_MAKEUP_INELIGIBLE` | 422 |
| `ERR_RECITAL_SOLD_OUT` | 409 |
| `ERR_FAMILY_DELINQUENT` | 402 |
| `ERR_NO_PAYMENT_METHOD` | 402 |
| `ERR_NOT_ENROLLED_IN_SECTION` | 422 |
| `ERR_INSUFFICIENT_CHAPERONES` | 422 |
| `ERR_DUPLICATE_INVOICE` | 409 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_CAPACITY_EXCEEDED` | 409 |
