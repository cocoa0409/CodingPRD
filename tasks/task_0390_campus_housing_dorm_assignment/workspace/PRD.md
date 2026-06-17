# Campus Housing & Dorm Assignment API — Product Requirements Document

## 1. Introduction

Residential life offices contend with a deceptively hard allocation problem every term: a finite inventory of beds, a population of students whose seniority and luck decide who is served first, and a web of downstream concerns — roommate compatibility, gender-inclusivity rules, meal plans, damage billing, safety incidents, and short-stay break housing — that all hang off whichever bed a student ultimately occupies. This API is the system of record for that entire pipeline. It manages building and room inventory, runs a seniority-and-lottery-driven offer engine each cycle, lets students form roommate groups and negotiate swaps, and tracks the money that flows when residents damage a room or stay over a break.

The design goal is determinism under contention. Offers are minted by a single batch lottery whose ordering is fully specified; waitlist promotion fills freed beds by a published precedence; and the few operations that two parties can race against each other — accepting a re-pointed offer, confirming a swap whose counterparty just cancelled — are guarded by optimistic concurrency so that a client acting on a stale view is rejected rather than silently overwriting a newer state. Throughout, money is tracked in integer cents and bed counts are reconciled as derived rollups, so the housing office can always reconcile what a building reports against the assignments and offers that produced it.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint. Domain-specific workflow detail lives in Section 3.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the operational capacity under which the request is made. The system recognizes exactly three roles, spelled precisely as `HousingOfficer`, `Student`, and `ResidentAdvisor`. A request missing either header, or carrying an `X-User-Role` that is not one of these three, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401); the same error applies when an entity-backed role omits `X-User-ID`. When a recognized, authenticated caller attempts an operation their role is not permitted to perform — or attempts to act on a resource they do not own — the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The three roles differ in how `X-User-ID` binds to data. When `X-User-Role` is `HousingOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may accept and record it for audit but never compares it against any entity's `id`. The `HousingOfficer` is housing-operations staff and owns inventory, the cycle and lottery, billing, vacate and check-out, incident resolution, and break approvals. When `X-User-Role` is `Student`, `X-User-ID` is the `id` of the acting `Student`; ownership checks on any resource that references a `Student` compare the resource's student foreign key to `X-User-ID`. A `Student` acts only on their own applications, their own roommate groups and memberships, their own assignments and swaps, their own meal plan, and their own break requests. When `X-User-Role` is `ResidentAdvisor`, `X-User-ID` is likewise the `id` of the acting `Student` (the RA is a student designated as an advisor); for incident operations the RA's `X-User-ID` is compared to the report's `reporter_student_id`. A resident advisor files and escalates incident reports.

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

List endpoints accept two query parameters. The `limit` parameter caps how many items are returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. A `limit` outside the range 1 through 100, or a negative `offset`, is rejected with `ERR_VALIDATION_PAGINATION` (HTTP 400).

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by `created_at` in ascending order. List responses carry `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Audit Fields

Every resource in the system is identified by an `id`, a server-minted UUID with no type prefix that serves as identity only. All entities also carry `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording first creation. Because every entity in this domain is mutable, each also carries an `updated_at` (an ISO 8601 UTC timestamp refreshed on every mutation, including cascaded mutations the server applies on the resource's behalf) and a `version`, an integer that starts at 1 on creation and increases by exactly 1 on every mutation. The `version` field underpins optimistic concurrency control as described in §2.7. Derived fields are not exempt: when the server recomputes a rollup such as a room's `occupied_bed_count` or a student's `account_balance_cents`, that recomputation is itself a mutation that refreshes `updated_at` and increments `version` on the affected resource.

### 2.5. Inventory Hierarchy, Derived Postures, and Bed Reconciliation

Inventory is the one strict hierarchy in the system: a `Building` owns `Room` records, and a room is always created beneath a known building so that its `building_id` is fixed from the path at creation time. Every other entity links by foreign key rather than nesting. When a request addresses a nested path — a room under a building, a membership under a group — the server validates the identifiers left to right, rejecting with `ERR_NOT_FOUND` (HTTP 404) at the first identifier in the path that names no existing resource. A room beneath a non-existent building therefore fails on the building before the room is ever consulted.

A room's `status` is a derived posture, never set directly except for the offline action. It takes one of three values: `OPEN`, `RESTRICTED`, or `OFFLINE`. A room is `RESTRICTED` when it is fully booked (its `occupied_bed_count` has reached its `bed_capacity`) or when it carries an open safety incident, as detailed in §3.7; it is `OPEN` when it has free beds and no open incidents and is not offline; and it becomes `OFFLINE` only through the explicit take-offline capability. Whenever an event changes a room's occupancy or its open-incident count, the server re-derives `status` and, because that is a mutation, refreshes `updated_at` and bumps `version`.

Bed counts are reconciled rollups, recomputed on any assignment status change, room offline or restore, lottery offer, offer accept, decline, or expire, and swap confirmation. A room's `occupied_bed_count` is the number of applications currently in `OFFERED` status whose `offered_room_id` is this room (offer reservations) plus the number of assignments on this room whose status is either `ACTIVE` or `SWAP_PENDING` (live residents — a swap-pending assignment still counts because its `room_id` does not change until the swap confirms). A building's `occupied_bed_count` is the sum of `occupied_bed_count` across its rooms, and its `total_bed_count` is the sum of `bed_capacity` across only those rooms whose status is not `OFFLINE`. A room's `open_incident_count` is the count of incident reports on the room whose status is `OPEN` or `ESCALATED`.

### 2.6. Monetary and Counting Precision

All monetary amounts in the system — damage assessments, meal-plan fees, break-housing charges, and student balances — are stored and returned as integer counts of cents; there are no fractional cents and no floating-point money. Where a charge must be divided among occupants, the division is integer floor division and the leftover remainder is assigned deterministically as described in §3.6, never spread or rounded away. Bed counts, night counts, and priority ranks are likewise plain integers. Night counts for break housing are whole nights computed by floor over a half-open date interval, as defined in §3.8.

### 2.7. Optimistic Concurrency Control

Two operations in this system can be raced against a state change a client has not yet observed, and both are guarded by optimistic concurrency. Each such write requires the caller to supply the version of the parent resource it last read; if that supplied version no longer matches the parent's current `version`, the write is rejected with `ERR_STALE_VERSION` (HTTP 412) before any effect is applied. Two further officer-only inventory writes — taking a room offline and restoring it — also require a matching room version under the same rule.

Accepting a lottery offer is guarded at the application level. The accept request must carry `expected_application_version` equal to the target application's current `version`. A sibling student declining their own offer can trigger a waitlist promotion that re-points or re-mints another offer and advances that application's `version`; a client that read the application earlier and then accepts on the old offer carries a stale `expected_application_version`, and the accept is rejected with `ERR_STALE_VERSION` (HTTP 412) on the version check before the accept applies. Confirming a swap is guarded at the assignment level. The confirm request must carry `expected_assignment_version` equal to the confirming assignment's current `version`; if the counterparty leg has since been cancelled, or the assignment has been vacated, that assignment's `version` has advanced, and a confirm carrying a stale `expected_assignment_version` is rejected with `ERR_STALE_VERSION` (HTTP 412) before the room exchange occurs. Taking a room offline and restoring a room each require `expected_room_version` matching the room's current `version`, again failing with `ERR_STALE_VERSION` (HTTP 412) on mismatch. No other endpoint accepts a version field, and endpoints not named here perform no version check.

### 2.8. Validation Ordering

When several checks could fail on one request, they are evaluated in a fixed precedence so the returned error is predictable. Authentication comes first: a missing or unknown role, or a missing identifier for an entity-backed role, yields `ERR_UNAUTHENTICATED` (HTTP 401). Authorization comes next: a role not permitted for the operation, or an ownership mismatch on an entity-backed write, yields `ERR_FORBIDDEN` (HTTP 403). Existence comes third: any referenced resource that does not exist, validated left to right across the path and body, yields `ERR_NOT_FOUND` (HTTP 404). Request well-formedness comes fourth: a missing required field, an invalid enum member, or an out-of-range integer yields `ERR_INVALID_REQUEST` (HTTP 400). Only after these gates do domain rules apply — date-range validity, state validity, cross-entity preconditions, gender compatibility, hold status, overlap and capacity ceilings, group sizing, settlement, duplicate prevention, and finally the optimistic-concurrency version check. The domain rules that share an endpoint are ordered as their individual workflows describe; where a workflow names more than one such rule, the order stated there is the order the server applies.

## 3. Business Logic & Workflows

### 3.1. Inventory: Buildings and Rooms

A `HousingOfficer` establishes inventory by creating a `Building` with a display `name` and a `building_type`, which is one of `TRADITIONAL`, `SUITE`, or `APARTMENT`. At creation the officer may also set `offers_break_housing`, a boolean that defaults to `false` and governs whether any room in the building may host break occupancy, and `break_housing_capacity`, a non-negative integer (it must be zero or greater) that defaults to 0 and caps the building's simultaneous approved break occupants as described in §3.8. A freshly created building reports `total_bed_count` of 0 and `occupied_bed_count` of 0; both are derived rollups maintained thereafter per §2.5.

Within a building, the officer creates rooms. A `Room` is created with a `room_number` (its label, unique within the building), a `room_type`, and a `gender_inclusivity` setting; the per-night break charge `nightly_break_rate_cents` may also be supplied and defaults to 4500. The `room_type` is one of `SINGLE`, `DOUBLE`, `TRIPLE`, or `SUITE_DOUBLE`, and it fixes the room's `bed_capacity`: a `SINGLE` has one bed, a `DOUBLE` has two, a `TRIPLE` has three, and a `SUITE_DOUBLE` has two. The `gender_inclusivity` is either `SINGLE_GENDER` or `ALL_GENDER` and constrains who may share the room, per §3.4. A new room begins with `status` of `OPEN`, an `occupied_bed_count` of 0, and an `open_incident_count` of 0. Rooms may be listed under their building as a convenience sub-resource view, and may also be listed across the system filtered by `building_id`; a single room may be fetched directly.

Taking a room offline is an officer-only capability that transitions its `status` to `OFFLINE`, but only when the room is empty — if `occupied_bed_count` is greater than 0 the request is rejected with `ERR_ROOM_OCCUPIED` (HTTP 409). The request must carry `expected_room_version` matching the room's current `version` (per §2.7). On success the room leaves the bed totals, so the owning building's `total_bed_count` is recomputed, and the room's `version` increments by 1. Restoring a room is the inverse officer-only capability: it re-derives the room's `status` from its current occupancy and open incidents (so a restored room becomes `OPEN` or `RESTRICTED` according to its posture, never staying `OFFLINE`), recomputes the building's `total_bed_count`, increments the room's `version` by 1, and likewise requires `expected_room_version` to match.

### 3.2. Students and Account Standing

A `HousingOfficer` registers each `Student` with a `full_name`, a `class_year`, a `gender_identity`, and a `lottery_number`. The `class_year` is one of `FRESHMAN`, `SOPHOMORE`, `JUNIOR`, or `SENIOR` and drives lottery priority. The `gender_identity` is one of `MALE`, `FEMALE`, or `NONBINARY` and is consulted in gender-inclusivity compatibility checks. The `lottery_number` is a caller-supplied draw value of at least 1 that serves as the tie-break seed among students of the same class year, where a smaller number wins. A new student starts in `status` `ACTIVE` with an `account_balance_cents` of 0.

A student's `status` is either `ACTIVE` or `HOLD`. The officer may place a student on hold, transitioning `status` from `ACTIVE` to `HOLD`, or release a hold, transitioning `status` from `HOLD` back to `ACTIVE`. A student on `HOLD` is blocked from submitting a new application or accepting an offer, as enforced in §3.3. The `account_balance_cents` is a derived ledger: it is the sum of the student's outstanding damage charges plus accrued break-housing charges, and it is debited and credited by the billing and break workflows described in §3.6 and §3.8.

### 3.3. The Housing Cycle and the Lottery

Allocation happens inside a `HousingCycle`, created by a `HousingOfficer` with a `term_label` such as `FALL_2026`. A cycle's `phase` is derived and advances only through the officer's batch actions; it begins at `APPLICATION_OPEN` and proceeds through `LOTTERY_RUN` and `ASSIGNMENT_OPEN` to the terminal `CLOSED`. The cycle also tracks `lottery_run_index`, a monotonic epoch counter that starts at 0.

A `Student` competes by first creating a draft `Application` that names the `cycle_id` it competes in, the applicant's `student_id`, a `preferred_building_type` (one of `TRADITIONAL`, `SUITE`, `APARTMENT`, or `NO_PREFERENCE`), and a `preferred_room_type` (one of `SINGLE`, `DOUBLE`, `TRIPLE`, `SUITE_DOUBLE`, or `NO_PREFERENCE`); an optional `roommate_group_id` may be supplied and otherwise defaults to null. A new application is created in `status` `DRAFT` with no `priority_rank` yet. A student may hold at most one non-terminal application per cycle — that is, no more than one application whose status is `DRAFT`, `SUBMITTED`, `OFFERED`, `ACCEPTED`, or `WAITLISTED`; a second such application in the same cycle is rejected with `ERR_DUPLICATE_APPLICATION` (HTTP 409). Applications may be fetched individually and listed filtered by `cycle_id`, `student_id`, `roommate_group_id`, or `offered_room_id`.

Submitting a draft moves it from `DRAFT` to `SUBMITTED` and computes its `priority_rank` from the applicant's class year by the priority rule: a `SENIOR` ranks 1, a `JUNIOR` ranks 2, a `SOPHOMORE` ranks 3, and a `FRESHMAN` ranks 4, where a lower rank is a better priority. The rank is stored on the application as its primary lottery sort key. Submission is permitted only while the cycle is in `APPLICATION_OPEN`; if not, the request fails with `ERR_INVALID_STATE` (HTTP 409). The applicant's student must be `ACTIVE` — a student on `HOLD` is rejected with `ERR_STUDENT_ON_HOLD` (HTTP 409). If the application names a `roommate_group_id`, the referenced group must be `LOCKED` and the submitting student must be an `ACCEPTED` member of it; otherwise the submission is rejected with `ERR_PRECONDITION_NOT_MET` (HTTP 409). A submitted application may be withdrawn while the cycle is in `APPLICATION_OPEN` or `LOTTERY_RUN`, moving it from `SUBMITTED` to the terminal `WITHDRAWN`; attempting this in another phase fails with `ERR_INVALID_STATE` (HTTP 409).

Running the lottery is the officer's batch action that advances the cycle from `APPLICATION_OPEN` to `LOTTERY_RUN`; attempting it from any other phase fails with `ERR_INVALID_STATE` (HTTP 409). It first increments `lottery_run_index` by 1. It then performs the offer selection over every application in `SUBMITTED` status in this cycle, processing them in a strict order: by `priority_rank` ascending first, then by the student's `lottery_number` ascending, then by `created_at` ascending. Walking the candidates in that order, the engine finds the rooms that match the candidate. A room matches when its `status` is `OPEN`, it has a free bed (its `occupied_bed_count` is below its `bed_capacity`), the candidate's `preferred_building_type` is either `NO_PREFERENCE` or equal to the room's building's `building_type`, the candidate's `preferred_room_type` is either `NO_PREFERENCE` or equal to the room's `room_type`, and the room's gender inclusivity permits the student (per §3.4). A candidate who states any non-`NO_PREFERENCE` preference is matched only against rooms satisfying every stated preference, and if no such room exists the candidate is waitlisted even though other open rooms remain; a candidate stating `NO_PREFERENCE` for both fields is matched against any open room with a free bed. Among matching rooms the engine picks the tightest fit first — the room with the fewest free beds (the smallest difference of `bed_capacity` minus `occupied_bed_count`), breaking ties by the room's `created_at` ascending. The chosen application moves from `SUBMITTED` to `OFFERED`, its `offered_room_id` is set to that room, and its `offer_lottery_index` is set to the current `lottery_run_index`; the reservation increments the room's `occupied_bed_count`, which may flip the room from `OPEN` to `RESTRICTED` once it reaches `bed_capacity`. A candidate with no matching room moves from `SUBMITTED` to `WAITLISTED`, and a `WaitlistEntry` in `QUEUED` status is created for it.

After the lottery the officer opens the assignment window, advancing the cycle from `LOTTERY_RUN` to `ASSIGNMENT_OPEN` (any other source phase fails with `ERR_INVALID_STATE`). Finally the officer closes the cycle, advancing it from `ASSIGNMENT_OPEN` to the terminal `CLOSED` (any other source phase fails with `ERR_INVALID_STATE`). Closing cascades over every application still in `OFFERED`: each moves to the terminal `EXPIRED`, its reserved bed is released (the room's `occupied_bed_count` decrements and the room's `status` may flip from `RESTRICTED` back to `OPEN`), and any still-`QUEUED` waitlist entry is simply left for the next cycle.

### 3.4. Gender Inclusivity Compatibility

Room sharing is governed by each room's `gender_inclusivity`. A room set to `ALL_GENDER` accepts any resident regardless of `gender_identity`. A room set to `SINGLE_GENDER` may only place together students who share a gender: a student whose `gender_identity` does not match the gender of the room's existing occupants may not be assigned there. This compatibility is checked when the lottery matches an application to a room, when a student accepts an offer, and on both rooms when a swap is proposed (each student must be compatible with the room they would move into). A violation at accept or at swap-proposal time is rejected with `ERR_GENDER_INCOMPATIBLE` (HTTP 409); during the lottery sweep an incompatible room simply does not match, so the candidate is offered another matching room or waitlisted.

### 3.5. Roommate Groups, Memberships, and Negotiation

Before the lottery, students may band together. A `Student` creates a `RoommateGroup` naming the `cycle_id` it competes in, the `owner_student_id` (the creator), and a `target_size` that must be between 2 and 3 inclusive, matching double and triple capacities. The group is created in `status` `FORMING`, the creator is enrolled as an auto-`ACCEPTED` member, and `accepted_member_count` therefore begins at 1. Groups may be fetched individually and listed filtered by `cycle_id` or `owner_student_id`.

The owner builds the group by inviting other students. Inviting a student creates a `RoommateMembership` under the group, with the group's `group_id` set from the path and the invited student's `student_id` recorded; the new membership begins in `membership_status` `INVITED`. A student may not be invited to a group where they already hold a membership in `INVITED` or `ACCEPTED` status; such a duplicate invite is rejected with `ERR_DUPLICATE_MEMBERSHIP` (HTTP 409). Memberships may be listed under their group as a convenience view, fetched individually, and listed across the system filtered by `group_id` or `student_id`.

Negotiation is a cyclic round of invites, accepts, and declines while the group stays `FORMING`. The invited student accepts, moving their membership from `INVITED` to `ACCEPTED` and incrementing the group's `accepted_member_count` by 1; acceptance is permitted only while the group is `FORMING`, only by the invited student themselves, and only while `accepted_member_count` is still below `target_size`. If the group is already full (its `accepted_member_count` already equals `target_size`), the accept is rejected with `ERR_GROUP_SIZE_INVALID` (HTTP 409). The invited student may instead decline, moving their membership from `INVITED` to the terminal `DECLINED`, again only while the group is `FORMING` and only by that student. The owner may remove an accepted member, moving that membership from `ACCEPTED` to the terminal `REMOVED` and decrementing `accepted_member_count` by 1; removal is permitted only while the group is `FORMING`, only by the owner, and the owner may not remove their own membership.

When the group is exactly full — its `accepted_member_count` equals its `target_size` — the owner may lock it, moving its `status` from `FORMING` to `LOCKED` and freezing membership so no further invite, accept, or decline is honored. Locking requires the count to equal the target exactly; a lock attempted when `accepted_member_count` does not equal `target_size` is rejected with `ERR_GROUP_SIZE_INVALID` (HTTP 409). The owner may reopen a locked group, moving it from `LOCKED` back to `FORMING` so membership becomes editable again, but only when no application referencing the group is in `SUBMITTED`, `OFFERED`, or `ACCEPTED` status; a reopen blocked by such an application fails with `ERR_PRECONDITION_NOT_MET` (HTTP 409). The owner may disband the group from either `FORMING` or `LOCKED`, moving it to the terminal `DISBANDED`, provided no application referencing the group is in `OFFERED` or `ACCEPTED` status (otherwise `ERR_PRECONDITION_NOT_MET`, HTTP 409). Disbanding moves every membership still in `INVITED` or `ACCEPTED` to `REMOVED`, and any `SUBMITTED` application that referenced the group keeps competing solo with its `roommate_group_id` cleared to null. All of lock, reopen, disband, and the membership accept, decline, and remove actions are owner-or-invitee operations restricted to the appropriate acting student; an action by the wrong student is `ERR_FORBIDDEN`, and an action against a group not in the required state is `ERR_INVALID_STATE` (HTTP 409).

### 3.6. Accepting an Offer, Assignments, Swaps, and Damage Billing

A student whose application is `OFFERED` accepts the offer during the assignment window. Acceptance moves the application from `OFFERED` to `ACCEPTED` and requires several conditions: the cycle must be in `ASSIGNMENT_OPEN`; the offer must not be stale, meaning the application's `offer_lottery_index` must still equal the cycle's current `lottery_run_index`; and the student must be `ACTIVE`. A non-`ASSIGNMENT_OPEN` phase or a wrong source status fails with `ERR_INVALID_STATE` (HTTP 409); a stale offer epoch fails with `ERR_PRECONDITION_NOT_MET` (HTTP 409); a student on `HOLD` fails with `ERR_STUDENT_ON_HOLD` (HTTP 409); and an incompatible room fails the gender check with `ERR_GENDER_INCOMPATIBLE` (HTTP 409). The request must also carry `expected_application_version` matching the application's current `version`, failing with `ERR_STALE_VERSION` (HTTP 412) on mismatch (per §2.7). On success the server mints an `Assignment` directly in `status` `ACTIVE` on the application's `offered_room_id` for this student, recording the assignment's `room_id`, `student_id`, and the producing `application_id`; it also creates a linked `MealPlan` in tier `STANDARD` and `status` `ACTIVE`; and the application's `version` increments by 1. The pre-accept reservation lives on the application (which holds `OFFERED`), not on any assignment, which is why a bed becomes a true assignment only at accept.

A student may instead decline an offer during the assignment window, moving the application from `OFFERED` to the terminal `DECLINED` (a non-`ASSIGNMENT_OPEN` phase fails with `ERR_INVALID_STATE`). Declining releases the offered bed — the room's `occupied_bed_count` decrements and its `status` may flip from `RESTRICTED` to `OPEN` — and then promotes the waitlist. Promotion selects, among the cycle's `QUEUED` waitlist entries, the entry with the best precedence — smallest `priority_rank_snapshot`, then smallest `lottery_number_snapshot`, then earliest `created_at` — whose application can match the freed room; that application moves from `WAITLISTED` to `OFFERED` on that room and the waitlist entry moves to `PROMOTED`. If no queued entry's application matches the freed room, the bed simply stays free.

Assignments may be fetched individually and listed filtered by `room_id`, `student_id`, `application_id`, or `swap_counterparty_assignment_id`. A resident may propose a room swap with another active assignment by supplying the `counterparty_assignment_id`. A swap proposal is permitted only by the proposing assignment's own student, only while the cycle is in `ASSIGNMENT_OPEN`, only when the counterparty assignment exists and is `ACTIVE`, and only when both rooms are gender-compatible with both students (per §3.4); a failed cross-entity precondition such as a non-`ACTIVE` counterparty is `ERR_PRECONDITION_NOT_MET` (HTTP 409). Proposing moves both assignments from `ACTIVE` to `SWAP_PENDING` and sets each assignment's `swap_counterparty_assignment_id` to the other. The confirming party — who must be the student on the leg that did not propose — confirms the swap, which requires that this assignment be `SWAP_PENDING` with its `swap_counterparty_assignment_id` set, and carries `expected_assignment_version` matching this assignment's current `version` (failing with `ERR_STALE_VERSION`, HTTP 412, on mismatch, per §2.7). Confirming exchanges the `room_id` between the two assignments, moves both back from `SWAP_PENDING` to `ACTIVE`, clears `swap_counterparty_assignment_id` on both, re-derives each room's `status`, and increments the confirming assignment's `version` by 1; the total occupied bed count is unchanged but each room's count is recomputed. Either party may cancel a pending swap, reverting both legs from `SWAP_PENDING` to `ACTIVE` and clearing `swap_counterparty_assignment_id` on both with no room change.

The officer may vacate an active assignment when a resident leaves mid-term, moving it from `ACTIVE` to `VACATED`; this releases the bed (the room's `occupied_bed_count` decrements and its `status` may flip from `RESTRICTED` to `OPEN`) and moves the linked meal plan from `ACTIVE` to `CANCELLED`. The officer checks out an assignment from either `ACTIVE` or `VACATED` to the terminal `CHECKED_OUT`. Check-out is blocked while any damage charge on the assignment is still `PENDING`; such a request is rejected with `ERR_UNSETTLED_CHARGES` (HTTP 409). On a permitted check-out the server computes `checkout_total_cents` as the sum of `amount_cents` over the assignment's damage charges whose status is `BILLED` or `PAID` (charges that are `WAIVED` or `PENDING` are excluded; since check-out is blocked while any are `PENDING`, the sum is taken over a settled set). If the assignment was still `ACTIVE` at check-out, the bed is also released, the room's `status` re-derived, and the linked meal plan moved from `ACTIVE` to `CANCELLED`.

Damage is billed against an assignment. The officer assesses a `DamageCharge` by naming the `assignment_id`, the `category` (one of `CLEANING`, `REPAIR`, `REPLACEMENT`, or `LOST_KEY`), the raw `assessed_cents` before any split, and the `split_basis` (either `SOLE` or `SHARED`). The new charge begins in `status` `PENDING`, copies the assignment's room into its own `room_id` for room-level tracking, and leaves `amount_cents` null until billed. Charges may be fetched individually and listed filtered by `assignment_id` or `room_id`. Billing a pending charge moves it from `PENDING` to `BILLED`, computes its final `amount_cents`, and debits the resident: the student's `account_balance_cents` increases by `amount_cents`. The split rule is: when `split_basis` is `SOLE`, the final `amount_cents` equals the full `assessed_cents` and the occupant count is ignored. When `split_basis` is `SHARED`, the server counts the assignments in `ACTIVE` status on the charge's room at the moment of billing; if that count is one or fewer, the final `amount_cents` is the full `assessed_cents`; otherwise the base share is `assessed_cents` divided by the occupant count using integer floor division, the remainder is `assessed_cents` minus the base times the occupant count, and the billed resident (this charge's assignment) is charged the base share plus that entire remainder. Alternatively the officer may waive a pending charge, moving it from `PENDING` to the terminal `WAIVED` and setting its `amount_cents` to 0 with no ledger change. A billed charge may be marked paid, moving it from `BILLED` to the terminal `PAID` and crediting the resident: the student's `account_balance_cents` decreases by `amount_cents`, but the balance is never allowed to fall below 0. Billing, waiving, and paying each require the charge to be in the correct source state (`PENDING` for bill and waive, `BILLED` for pay); otherwise the request fails with `ERR_INVALID_STATE` (HTTP 409).

### 3.7. Incidents and Room Restriction

A `ResidentAdvisor` files an `IncidentReport` against a room by naming the `room_id`, the `reporter_student_id` (the filing RA's own student id), and a `severity` of `MINOR`, `MAJOR`, or `CRITICAL`. A new report begins in `status` `OPEN`, increments the room's `open_incident_count` by 1, and re-derives the room's `status`: a `CRITICAL` incident restricts the room, moving it to `RESTRICTED`. Incident reports may be fetched individually and listed filtered by `room_id` or `reporter_student_id`. Both filing and escalation are RA operations, and ownership is enforced by comparing the RA's `X-User-ID` to the report's `reporter_student_id`.

The filing RA may escalate an open report, moving it from `OPEN` to `ESCALATED`; escalation is permitted only while the report is `OPEN` and only by the reporter (a wrong source state is `ERR_INVALID_STATE`, HTTP 409). An escalated report still counts as open, so the room's `open_incident_count` is unchanged, but the room's `status` is re-derived, which may restrict the room. The `HousingOfficer` resolves a report from either `OPEN` or `ESCALATED` to the terminal `RESOLVED`; resolution decrements the room's `open_incident_count` by 1 and may flip the room from `RESTRICTED` back to `OPEN` when no open incidents remain and the room carries no offline flag.

### 3.8. Meal Plans and Break Housing

Every accepted offer mints a `MealPlan` linked one-to-one to the new assignment by its `assignment_id`, beginning in tier `STANDARD` and `status` `ACTIVE`. A plan's `weekly_fee_cents` is derived from its `tier`: a `NONE` tier costs 0, a `COMMUTER` tier costs 4000, a `STANDARD` tier costs 9000, and an `UNLIMITED` tier costs 13500. The owning student may change the plan's `tier` while it is `ACTIVE`, supplying a new `tier`, which recomputes `weekly_fee_cents` from the table above; tier edits are not honored once the plan is `CANCELLED`. A plan's `status` is `ACTIVE` or `CANCELLED`, and it moves to `CANCELLED` only when its assignment leaves `ACTIVE` — that is, on vacate or check-out (per §3.6) — never by direct request. Meal plans may be fetched individually and listed filtered by `assignment_id`.

Waitlist entries are read-only artifacts of the lottery and decline workflows. A `WaitlistEntry` records the `cycle_id` it scopes to and the `application_id` it represents, and at the moment it is queued it captures `priority_rank_snapshot` (a copy of the application's `priority_rank`) and `lottery_number_snapshot` (a copy of the student's `lottery_number`); these snapshots are the queue's sort keys, both ascending. Its `status` is `QUEUED`, `PROMOTED`, or `CANCELLED`. Entries may be fetched individually and listed filtered by `cycle_id` or `application_id`.

Break housing lets a resident stay over a break in their assigned room. A `Student` requests it by naming the `assignment_id` of their term assignment, a `check_in_date`, and a `check_out_date`, each a date at midnight UTC; the request copies the assignment's room into its own `room_id` and computes `night_count`, but does not charge anything yet, beginning in `status` `REQUESTED`. The `check_out_date` must be strictly after the `check_in_date`; a check-out that is not strictly later is rejected at validation with `ERR_INVALID_DATE_RANGE` (HTTP 422), and such a request can never be approved. The `night_count` is the number of whole nights in the half-open interval from `check_in_date` up to but not including `check_out_date`, computed as the floored count of whole days between the two dates. Break requests may be fetched individually and listed filtered by `assignment_id` or `room_id`.

The officer approves a requested break, moving it from `REQUESTED` to `APPROVED`, subject to several gates. The room's building must offer break housing (its `offers_break_housing` must be true); a building that does not is rejected with `ERR_PRECONDITION_NOT_MET` (HTTP 409). The requested interval must not overlap any existing `APPROVED` break interval on the same room: treating each interval as half-open from check-in up to but not including check-out, two intervals conflict when they share any instant, while exact adjacency (one interval's check-out equal to the next interval's check-in) is allowed; an overlap is rejected with `ERR_BREAK_OVERLAP` (HTTP 409). The building's aggregate capacity must also hold: at every instant within the requested interval, the count of `APPROVED` break requests across all rooms of the same building that overlap that instant, plus this one, must not exceed the building's `break_housing_capacity`; exceeding it is rejected with `ERR_BREAK_CAPACITY_EXCEEDED` (HTTP 409). On approval the server computes `total_charge_cents` as `night_count` multiplied by the room's `nightly_break_rate_cents` and debits the resident: the student's `account_balance_cents` increases by `total_charge_cents`. The officer may instead deny a requested break, moving it from `REQUESTED` to the terminal `DENIED`. The requesting resident may cancel their break from either `REQUESTED` or `APPROVED`, moving it to the terminal `CANCELLED`; if the break was `APPROVED`, the charge is refunded, decreasing the student's `account_balance_cents` by `total_charge_cents` but never below 0.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — including state-transition actions and tier edits — return `200 OK`. The full request and response shape for each endpoint is reconstructed from the Section 3 narratives; the table below lists only the route, its purpose, and the roles permitted to call it.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/buildings` | Create a building | HousingOfficer |
| GET | `/buildings/{building_id}` | Get a building | HousingOfficer, Student, ResidentAdvisor |
| POST | `/buildings/{building_id}/rooms` | Create a room in a building | HousingOfficer |
| GET | `/buildings/{building_id}/rooms` | List rooms in a building | HousingOfficer, Student, ResidentAdvisor |
| GET | `/rooms` | List rooms, filterable by building | HousingOfficer, Student, ResidentAdvisor |
| GET | `/rooms/{room_id}` | Get a room | HousingOfficer, Student, ResidentAdvisor |
| POST | `/rooms/{room_id}/take-offline` | Mark a room offline | HousingOfficer |
| POST | `/rooms/{room_id}/restore` | Restore an offline room | HousingOfficer |
| POST | `/students` | Register a student | HousingOfficer |
| GET | `/students/{student_id}` | Get a student | HousingOfficer, Student, ResidentAdvisor |
| POST | `/students/{student_id}/place-hold` | Put a student on hold | HousingOfficer |
| POST | `/students/{student_id}/release-hold` | Release a student hold | HousingOfficer |
| POST | `/housing-cycles` | Create a housing cycle | HousingOfficer |
| GET | `/housing-cycles/{cycle_id}` | Get a housing cycle | HousingOfficer, Student, ResidentAdvisor |
| POST | `/housing-cycles/{cycle_id}/run-lottery` | Run the lottery for the cycle | HousingOfficer |
| POST | `/housing-cycles/{cycle_id}/open-assignment` | Open the assignment window | HousingOfficer |
| POST | `/housing-cycles/{cycle_id}/close` | Close the cycle | HousingOfficer |
| POST | `/applications` | Create a draft application | Student |
| GET | `/applications/{application_id}` | Get an application | HousingOfficer, Student, ResidentAdvisor |
| GET | `/applications` | List applications | HousingOfficer, Student, ResidentAdvisor |
| POST | `/applications/{application_id}/submit` | Submit a draft application | Student |
| POST | `/applications/{application_id}/withdraw` | Withdraw a submitted application | Student |
| POST | `/applications/{application_id}/accept` | Accept the lottery offer | Student |
| POST | `/applications/{application_id}/decline` | Decline the lottery offer | Student |
| POST | `/roommate-groups` | Create a roommate group | Student |
| GET | `/roommate-groups/{group_id}` | Get a roommate group | HousingOfficer, Student, ResidentAdvisor |
| GET | `/roommate-groups` | List roommate groups | HousingOfficer, Student, ResidentAdvisor |
| POST | `/roommate-groups/{group_id}/memberships` | Invite a student into a group | Student |
| GET | `/roommate-groups/{group_id}/memberships` | List memberships of a group | HousingOfficer, Student, ResidentAdvisor |
| GET | `/roommate-memberships/{membership_id}` | Get a roommate membership | HousingOfficer, Student, ResidentAdvisor |
| GET | `/roommate-memberships` | List roommate memberships | HousingOfficer, Student, ResidentAdvisor |
| POST | `/roommate-groups/{group_id}/memberships/{membership_id}/accept` | Accept a membership | Student |
| POST | `/roommate-groups/{group_id}/memberships/{membership_id}/decline` | Decline a membership | Student |
| POST | `/roommate-groups/{group_id}/memberships/{membership_id}/remove` | Remove an accepted member | Student |
| POST | `/roommate-groups/{group_id}/lock` | Lock a full forming group | Student |
| POST | `/roommate-groups/{group_id}/reopen` | Reopen a locked group | Student |
| POST | `/roommate-groups/{group_id}/disband` | Disband a group | Student |
| GET | `/assignments/{assignment_id}` | Get an assignment | HousingOfficer, Student, ResidentAdvisor |
| GET | `/assignments` | List assignments | HousingOfficer, Student, ResidentAdvisor |
| POST | `/assignments/{assignment_id}/propose-swap` | Propose a room swap | Student |
| POST | `/assignments/{assignment_id}/confirm-swap` | Confirm a pending swap | Student |
| POST | `/assignments/{assignment_id}/cancel-swap` | Cancel a pending swap | Student |
| POST | `/assignments/{assignment_id}/vacate` | Vacate an assignment | HousingOfficer |
| POST | `/assignments/{assignment_id}/check-out` | Check out an assignment | HousingOfficer |
| GET | `/meal-plans/{meal_plan_id}` | Get a meal plan | HousingOfficer, Student, ResidentAdvisor |
| GET | `/meal-plans` | List meal plans | HousingOfficer, Student, ResidentAdvisor |
| PATCH | `/meal-plans/{meal_plan_id}` | Change a meal plan tier | Student |
| GET | `/waitlist-entries/{entry_id}` | Get a waitlist entry | HousingOfficer, Student, ResidentAdvisor |
| GET | `/waitlist-entries` | List waitlist entries | HousingOfficer, Student, ResidentAdvisor |
| POST | `/damage-charges` | Assess a damage charge | HousingOfficer |
| GET | `/damage-charges/{charge_id}` | Get a damage charge | HousingOfficer, Student, ResidentAdvisor |
| GET | `/damage-charges` | List damage charges | HousingOfficer, Student, ResidentAdvisor |
| POST | `/damage-charges/{charge_id}/bill` | Bill a pending charge | HousingOfficer |
| POST | `/damage-charges/{charge_id}/waive` | Waive a pending charge | HousingOfficer |
| POST | `/damage-charges/{charge_id}/pay` | Mark a billed charge paid | HousingOfficer |
| POST | `/incident-reports` | File an incident report | ResidentAdvisor |
| GET | `/incident-reports/{incident_id}` | Get an incident report | HousingOfficer, ResidentAdvisor |
| GET | `/incident-reports` | List incident reports | HousingOfficer, ResidentAdvisor |
| POST | `/incident-reports/{incident_id}/escalate` | Escalate an open incident | ResidentAdvisor |
| POST | `/incident-reports/{incident_id}/resolve` | Resolve an incident | HousingOfficer |
| POST | `/break-housing-requests` | Request break housing | Student |
| GET | `/break-housing-requests/{request_id}` | Get a break housing request | HousingOfficer, Student, ResidentAdvisor |
| GET | `/break-housing-requests` | List break housing requests | HousingOfficer, Student, ResidentAdvisor |
| POST | `/break-housing-requests/{request_id}/approve` | Approve a break request | HousingOfficer |
| POST | `/break-housing-requests/{request_id}/deny` | Deny a break request | HousingOfficer |
| POST | `/break-housing-requests/{request_id}/cancel` | Cancel a break request | Student |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_DATE_RANGE` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PRECONDITION_NOT_MET` | 409 |
| `ERR_GENDER_INCOMPATIBLE` | 409 |
| `ERR_STUDENT_ON_HOLD` | 409 |
| `ERR_BREAK_OVERLAP` | 409 |
| `ERR_BREAK_CAPACITY_EXCEEDED` | 409 |
| `ERR_GROUP_SIZE_INVALID` | 409 |
| `ERR_UNSETTLED_CHARGES` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_ROOM_OCCUPIED` | 409 |
| `ERR_DUPLICATE_MEMBERSHIP` | 409 |
| `ERR_DUPLICATE_APPLICATION` | 409 |
| `ERR_VALIDATION_PAGINATION` | 400 |
