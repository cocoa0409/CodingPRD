# Equestrian Show Management API — Product Requirements Document

## 1. Introduction

A licensed horse show is three businesses running at once. It is a regulated event that only exists once the national federation stamps its prize list; it is a logistics operation that has to move several hundred horses through a handful of rings on a schedule that nobody can predict precisely; and it is a scoring authority whose output — ribbons, purse cheques and standings points — feeds registries that riders chase for an entire season. Today the show office reconciles all three by hand, on paper prize lists and whiteboard ring orders, and the seams show: an entry gets a stall it was never allocated, a judge is carded into two rings at once, a class's purse is paid out twice because the void was recorded only in pencil, and points reach the regional affiliate for a class that was later disqualified.

This document specifies the backend service that replaces that reconciliation. The service owns the whole arc from licence application through to standings acknowledgement, and it treats the arc as a set of ledgers that must balance rather than as a sequence of forms. Prize money is a conserved quantity: every cent posted to a ribbon must be visible as allocated against the show's pool, and every cent released by a void must return to the unallocated side with no drift. Stalls behave the same way. Officials carry a licence envelope and a daily minute budget that the service refuses to overspend. And because the federation is a separate body with its own review cycle, licensing, standings acknowledgement and compliance adjudication are all modelled as decisions that arrive from outside and can revert work the show office has already done.

Two design constraints run through everything that follows. First, the service is time-driven but must be testable, so every temporal rule — membership lapse, Coggins validity, entry window closure, coverage check-in — is evaluated against a server-held logical clock rather than wall-clock time. Second, several of the most damaging real-world errors are not invalid inputs but stale views: a ring master booking a class into a running order that has already been renumbered, or a secretary submitting standings for a class whose results have since been withdrawn. Those are handled by explicit optimistic concurrency on the two write paths where an ordered, single-artifact resource is at stake.

---

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API — reads included — must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the role the caller is acting in. If either header is absent, or if `X-User-Role` is not one of the seven role names declared below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If both headers are present and well-formed but the named role is not among the roles authorised for the requested operation, the rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP 403).

The seven roles are `ShowSecretary`, `FederationOfficer`, `RingMaster`, `Judge`, `Steward`, `Exhibitor` and `GroundsManager`. Their responsibilities partition the system deliberately, and the partition is a segregation-of-duties control rather than a convenience:

- A **`ShowSecretary`** is the show office. It creates shows, builds the prize list (rings, divisions and classes), drives licence submissions, opens classes, cards officials, processes entry verification, acceptance and invoicing, posts and voids class results, and raises standings submissions.
- A **`FederationOfficer`** is national federation staff. It decides show licences, maintains the official, rider and horse registries, records standings-body acknowledgements, adjudicates compliance findings, and drives the logical clock. It cannot build a prize list or process entries.
- A **`RingMaster`** owns in-gate operations: booking classes into rings and calling them in. It can neither create the classes it schedules nor judge them.
- A **`Judge`** records the card for a class on whose slot it holds the judging chair.
- A **`Steward`** opens drug-test and welfare-citation cases but never adjudicates them; the finding belongs to the `FederationOfficer`.
- An **`Exhibitor`** is a competitor: it submits its own entries, enters classes, pays invoices and withdraws.
- A **`GroundsManager`** maintains footing and schedules and checks in veterinary and farrier coverage. It cannot schedule competition or touch results.

All seven roles may call every read (`GET`) endpoint in the system. Write authority is exclusive per the table in §4.

Identity semantics differ by role, and they matter because ownership checks compare `X-User-ID` against stored foreign keys:

- When `X-User-Role` is `Exhibitor`, `X-User-ID` is the `id` of the acting `Rider`; ownership checks on any resource that references a `Rider` compare the resource's rider foreign-key field to `X-User-ID`. Concretely, an `Exhibitor` acting on an entry must be the entry's `rider_id`, and a mismatch is `ERR_ENTRY_NOT_OWNED` (HTTP 403).
- When `X-User-Role` is `Judge`, `X-User-ID` is the `id` of the acting `Official`; the judging-chair check compares the officials carded on the relevant slot to `X-User-ID`.
- When `X-User-Role` is `Steward`, `X-User-ID` is likewise the `id` of the acting `Official`.
- For those three entity-backed roles, `X-User-ID` must resolve to an existing row of the backing entity — an existing `Rider` for `Exhibitor`, an existing `Official` for `Judge` and `Steward`. When it does not, the request fails with `ERR_ACTOR_NOT_RECOGNIZED` (HTTP 403).
- When `X-User-Role` is `ShowSecretary`, `FederationOfficer`, `RingMaster` or `GroundsManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — a standings submission stores the raising secretary's identifier in `submitted_by_user_id` — but it never compares it to any entity's `id`, and no ownership check is derived from it.

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

### 2.3. Pagination

Every collection endpoint accepts two optional query parameters. `limit` defaults to 10, may be no smaller than 1 and no larger than 100. `offset` defaults to 0 and has no upper bound beyond the size of the collection. Both are echoed in the `meta` block of the response alongside `total_count` — the number of rows matching the request's filters before the window is applied — and `has_more`, which is true when rows remain after the current window.

Unless a subsection below states otherwise, list results are ordered by `created_at` ascending. Filters supplied alongside pagination narrow the collection before the window is taken, so `total_count` reflects the filtered population and not the whole table.

### 2.4. Collection Filters

Filters are exact-match on the named field and may be combined; supplying none returns the whole collection. The available filters, by collection, are:

- Rings of a show: `status`.
- Competition divisions of a show: `status` and `discipline`.
- Coverage shifts of a show: `coverage_type` and `status`.
- Classes: `division_id`, `qualifier_for_class_id` and `status`. The `qualifier_for_class_id` filter is how a caller discovers which classes feed a given championship class.
- Standings submissions of a class: `status`. This collection is the only channel through which a submission's `id` becomes known to a client.
- Ring slots: `ring_id`, `class_id`, `slot_type` and `status`. This collection is the only channel through which maintenance slots synthesised by footing work become visible.
- Official assignments: `official_id`, `slot_id`, `official_role` and `status`.
- Entries: `show_id`, `rider_id`, `horse_id`, `verification_status` and `settlement_status`.
- Class entries: `entry_id`, `class_id` and `status`.
- Compliance cases: `entry_id`, `opened_by_official_id`, `case_type` and `status`.
- A rider's standings read accepts an optional `show_id` to scope the recomputation to a single show.

### 2.5. Common Resource Properties

Every persisted resource carries a server-minted `id`: a UUID with no type prefix, assigned at creation and never reused or rewritten. Clients never supply an `id`.

Every resource also carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits recorded at insertion and never modified afterwards. Every resource in this system additionally carries `updated_at` — same format, rewritten on every mutation — and `version`, an integer that begins at 1 on creation and increments by exactly one each time the resource is mutated. There are no exceptions: all fourteen resource types (shows, rings, competition divisions, classes, ring slots, officials, official assignments, riders, horses, entries, class entries, standings submissions, compliance cases and coverage shifts) expose all four common properties.

The `version` counter is not decorative. Because this system's operations routinely mutate several resources at once, a single request can advance the `version` of a resource the caller never named — and that is exactly what the concurrency controls in §2.7 read. Whenever a workflow narrative in §3 says a counter or a status on some other resource was recomputed, that other resource's `version` advanced by one and its `updated_at` was refreshed.

### 2.6. The Logical Show Clock

Time in this service is a server-held value, not the host's wall clock. On startup the logical current instant is exactly `2026-08-01T00:00:00Z`, and it stays there until a `FederationOfficer` moves it by supplying a `to_iso8601` instant to the clock-setting capability described in §4. The service never falls back to real time, not even before the first clock call. The response to a clock write reports the new instant as `current_utc`.

Every temporal rule reads this clock: whether a rider's federation membership has lapsed, whether an entry arrives before the show's entry window closes, and whether a coverage provider is checking in too early. Moving the clock mutates no entity and advances no `version`; the effects are purely derivational, which is why a rider's `membership_status` is recomputed on every read rather than stored as a settled fact.

### 2.7. Optimistic Concurrency on Running Orders and Standings Submissions

Two write paths in this system operate on artifacts whose whole meaning is their ordering or their finality, and both require the client to prove it was looking at a current view.

Booking a class into a ring — `POST /ring-slots` — requires `expected_ring_version` in the request body, carrying the client's last observed `version` of the target ring. It is not optional. The value must equal the target `Ring`'s current `version`; when it does not, the booking is rejected with `ERR_STALE_VERSION` (HTTP 412). The reason is that a ring's running order is one ordered artifact: any earlier accepted booking, or a footing-maintenance hold, renumbers `order_index` across the whole ring and legitimately supersedes the layout the current writer was reading. A writer holding a stale ring version is refused rather than silently reordered.

Raising a standings submission for a class — `POST /classes/{id}/point-submissions` — requires `expected_class_version` in the request body, carrying the client's last observed `version` of the target class. It too is non-optional, is compared against the target `ShowClass`'s current `version`, and is rejected with `ERR_STALE_VERSION` (HTTP 412) on mismatch. A corrected submission is allowed to supersede an earlier rejected one, so a second submission against the same class is legitimate product behaviour; the version check is what distinguishes "I know about the prior submission and am replacing it" from "my view of this class predates the prior submission".

No other endpoint takes a version field. Requests to endpoints outside these two must not be expected to carry one, and none of them performs a version comparison.

### 2.8. Path Resolution and Referential Integrity

Path segments are resolved strictly left to right, and the first segment that does not resolve determines the error. A request naming a division inside a show that does not exist reports the missing show, never the missing division. The not-found codes are per resource type: `ERR_SHOW_NOT_FOUND`, `ERR_RING_NOT_FOUND`, `ERR_DIVISION_NOT_FOUND`, `ERR_CLASS_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`, `ERR_CLASS_ENTRY_NOT_FOUND`, `ERR_OFFICIAL_NOT_FOUND`, `ERR_RIDER_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_POINT_SUBMISSION_NOT_FOUND`, `ERR_COMPLIANCE_CASE_NOT_FOUND` and `ERR_COVERAGE_SHIFT_NOT_FOUND`. All carry HTTP 404.

The same catalogue serves references supplied inside a request body rather than in the path. Every foreign key in a payload must resolve to an existing row before any business rule is consulted, and the code names the missing type: a `show_id` that resolves to nothing is `ERR_SHOW_NOT_FOUND`, a `ring_id` is `ERR_RING_NOT_FOUND`, a `class_id` or a `qualifier_for_class_id` is `ERR_CLASS_NOT_FOUND`, a `slot_id` is `ERR_SLOT_NOT_FOUND`, an `entry_id` is `ERR_ENTRY_NOT_FOUND`, an `official_id` or an `opened_by_official_id` is `ERR_OFFICIAL_NOT_FOUND`, a `rider_id` is `ERR_RIDER_NOT_FOUND`, a `horse_id` is `ERR_HORSE_NOT_FOUND`, and a `class_entry_id` named inside a judge's card is `ERR_CLASS_ENTRY_NOT_FOUND`. Body-reference resolution applies to the seven creating operations that carry foreign keys: ring-slot booking, official carding, entry submission, class-entry creation, class creation under a division, compliance-case opening, and results recording.

Payload shape itself is checked before any of this: required fields present, enum values drawn from their declared member sets, integers inside their declared ranges, datetimes parseable as ISO 8601, and conditionally required fields honoured. A violation is `ERR_INVALID_REQUEST` (HTTP 422). The conditional rule that matters most in practice concerns compliance cases: `sample_code` is required when `case_type` is `DRUG_TEST` and must be omitted otherwise, while `welfare_rule_code` is required when `case_type` is `WELFARE_CITATION` and must be omitted otherwise.

### 2.9. Precision, Rounding and Units

Money is stored and transmitted as whole cents in integer fields; there are no fractional-cent values anywhere in the system. Wherever a monetary figure is derived by applying a basis-point share, the result is rounded half up to a whole number of cents. "Half up" means a value whose fractional part is exactly one half rounds away from zero.

Durations are whole minutes. Where a duration is derived from a figure in seconds, the conversion rounds up to the next whole minute, and — this is load-bearing — the rounding happens exactly once, after all multiplication is complete. Rounding each component and then adding is not the specified order and yields different answers.

Datetime values are ISO 8601 UTC at second granularity. Interval arithmetic is expressed in whole minutes.

Standings points are the one non-integer quantity. National points are carried to one decimal place and rounded half up; regional points are always whole numbers.

Stall counts and official minute loads are plain integers with no rounding.

### 2.10. Conserved Ledgers

Two aggregate ledgers in this system are conserved quantities, and every forward action has a compensating action that returns them to their exact prior value with zero drift.

The **stall ledger** on a show maintains `reserved_stall_count` as the sum of `assigned_stall_count` across all of that show's entries whose `verification_status` is `ACCEPTED`, and `available_stall_count` as `stall_capacity` minus `reserved_stall_count`. Entries in `RECEIVED`, `VERIFIED` or `WITHDRAWN` contribute zero regardless of what they requested. The invariant `stall_capacity` equals `reserved_stall_count` plus `available_stall_count` holds before and after every acceptance and every withdrawal.

The **prize ledger** on a show maintains `allocated_prize_cents` as the sum of `awarded_prize_cents` across classes of the show whose `status` is `RESULTS_POSTED` or `POINTS_SUBMITTED`, and `unallocated_prize_cents` as `prize_money_pool_cents` minus `allocated_prize_cents`. Classes that are merely `JUDGED`, classes that are `VOIDED`, and classes that have not yet been judged all contribute zero. The invariant `prize_money_pool_cents` equals `allocated_prize_cents` plus `unallocated_prize_cents` holds before and after every posting and every void. Posting adds exactly the class's `awarded_prize_cents`; voiding subtracts exactly the same amount.

A third aggregate on the show, `division_share_bp_total`, sums `division_share_bp` over the show's divisions whose `status` is `ACTIVE`. It is recomputed when a division is added and again at licence submission, and it may never exceed 10000 basis points.

A fourth aggregate lives on the official: `assigned_minutes` sums, over that official's assignments whose `status` is `ACTIVE`, the whole minutes from the assigned slot's `warmup_start_utc` to its `end_utc`. Carding an official increments it; releasing an assignment decrements it by exactly the same figure.

### 2.11. Cascade Discipline

Several operations in this system are the head of a multi-level cascade — a footing failure unwinds a ring's schedule and the officials carded on it; a positive compliance finding unwinds disqualifications, class results, the show's prize ledger and any standings submission already in flight. Cascades are specified in §3 alongside the workflows that trigger them, and three rules govern all of them.

First, cascades run to completion within the triggering request. There is no deferred or eventual step; by the time the response is written, every downstream resource has reached its new state.

Second, every resource a cascade touches has its `version` incremented by one and its `updated_at` refreshed — including resources the caller never named and resources whose only change was a recomputed counter.

Third, cascades are not symmetric with their triggers. Reversing the trigger does not resurrect what the cascade destroyed. Bringing a ring back out of a maintenance hold does not un-cancel the slots the hold cancelled; those must be booked again.

### 2.12. Validation Precedence

When more than one rule would reject a request, the earlier rule in the following ladder wins, and its error is the one returned. The ordering is normative: a request that violates several rules must report the first violation in this sequence, not the most specific one and not the last one evaluated.

1. Header presence and role recognition — `ERR_UNAUTHENTICATED`.
2. Role authorisation for the endpoint — `ERR_ROLE_NOT_PERMITTED`.
3. Existence of every path-segment resource, left to right — the per-type 404 codes of §2.8.
4. Resolution of `X-User-ID` for the entity-backed roles — `ERR_ACTOR_NOT_RECOGNIZED`.
5. Existence of every foreign key supplied in the request body — the per-type 404 codes of §2.8.
6. Request-body shape, enum membership, integer ranges, datetime parseability and the conditional-field rules — `ERR_INVALID_REQUEST`.
7. `Exhibitor` ownership of the entry being acted on — `ERR_ENTRY_NOT_OWNED`.
8. The optimistic-concurrency version match of §2.7 — `ERR_STALE_VERSION`.
9. The target resource's own state precondition — the 409 state codes.
10. The cross-entity licence gate — `ERR_SHOW_LICENSE_NOT_APPROVED` or `ERR_SHOW_LICENSE_LOCKED`.
11. Safety, welfare and licence-sufficiency rules (rider membership, Coggins validity, horse eligibility, official licence coverage, footing safety, veterinary coverage, the required-officials matrix, the welfare strike limit) — in that internal order.
12. Referential and integrity rules (conflict of interest, judging-chair possession, segregation of duties, qualifier-chain acyclicity) — in that internal order.
13. Temporal rules (entry window, slot containment in the show window, ring overlap geometry, official overlap geometry) — in that internal order.
14. Capacity and shape constraints (jump-height band, class-number uniqueness, division share, class fullness, duplicate class entry, official load ceiling, entries present to judge, placings validity, point eligibility, class-list completeness, coverage check-in lead, finding applicability).
15. Fiscal constraints (stall capacity, prize-pool headroom, unpaid placed entries, payment amount match).

Within band 11 the order is: rider membership lapse, then Coggins expiry, then horse suspension, then official licence sufficiency, then footing safety, then veterinary coverage, then the required-officials matrix, then the welfare strike limit. Within band 12: conflict of interest, then judging-chair possession, then segregation of duties, then qualifier-chain acyclicity. Within band 13: entry window closure, then slot containment, then ring overlap, then official overlap.

---

## 3. Business Logic & Workflows

### 3.1. Licensing a Show and Freezing Its Prize List

A show is born in the show office. A `ShowSecretary` creates it with the `name` that will be printed on the prize list, the `federation_show_id` applied for on the licence, the `venue` at which it will run, and the `competition_level` at which it is being held — one of `LOCAL`, `REGIONAL`, `NATIONAL` or `PREMIER`, a choice that later dictates both how many officials each class needs and how highly licensed those officials must be. Three instants bound the show: `start_utc`, the first moment of competition and the instant against which every horse's Coggins validity is measured; `end_utc`, the last moment of competition, inside which every ring slot must fall; and `entry_close_utc`, at which the entry window shuts. The window is exclusive at its upper end — an entry arriving exactly at `entry_close_utc` is too late.

Money and stabling are declared up front. `prize_money_pool_cents` is the total purse the organizer has posted, in cents, and may not be negative. `stall_capacity` is the number of stalls on the grounds and `stall_fee_cents` the per-stall charge that will appear on entry invoices; neither may be negative. At creation the show's `license_status` is `DRAFT`, `revision_count` is 0, `allocated_prize_cents` is 0, `unallocated_prize_cents` equals `prize_money_pool_cents`, `reserved_stall_count` is 0, `available_stall_count` equals `stall_capacity`, `division_share_bp_total` is 0 and `welfare_strike_count` is 0.

The licence itself is a cycle, not a straight line. `license_status` moves `DRAFT → SUBMITTED` when the secretary submits the prize list to the federation, and submission is only accepted from `DRAFT` or from `RETURNED_FOR_CORRECTION`; attempting it from `SUBMITTED`, `APPROVED` or `DENIED` yields `ERR_SHOW_LICENSE_NOT_DRAFT`. Submission from either origin requires the prize list to be substantive: the show must have at least one `CompetitionDivision` whose `status` is `ACTIVE` and at least one class beneath its divisions, or the submission fails with `ERR_CLASS_LIST_INCOMPLETE`. It also requires `division_share_bp_total` — recomputed as part of the submission — to be no greater than 10000 basis points, failing which the answer is `ERR_DIVISION_SHARE_OVERSUBSCRIBED`. A successful submission increments the show's `version`. When the origin was `RETURNED_FOR_CORRECTION`, the transition `RETURNED_FOR_CORRECTION → SUBMITTED` additionally adds one to `revision_count`; that counter is the loop counter the federation will test on its next return decision.

The federation's decision arrives from a `FederationOfficer` as one of three values in a `decision` field: `APPROVE`, `RETURN` or `DENY`, optionally accompanied by a `correction_note`. All three require the show to be in `SUBMITTED`; from any other licence state the decision is refused with `ERR_SHOW_LICENSE_NOT_SUBMITTED`.

`RETURN` has two outcomes, and which one applies is decided by `revision_count` alone. While `revision_count` is strictly less than 2, the show moves `SUBMITTED → RETURNED_FOR_CORRECTION`, the supplied `correction_note` is stored against the licence record, and `version` increments. Once `revision_count` has reached 2, the federation refuses a third correction cycle outright: the show moves `SUBMITTED → DENIED` instead, with the same consequences as an explicit denial. This escalation is automatic and requires no different input from the officer.

`DENY` moves the show `SUBMITTED → DENIED` directly. Denial — whether explicit or escalated — closes the prize list: every `CompetitionDivision` of the show whose `status` is `ACTIVE` becomes `CLOSED`, and every class beneath those divisions whose `status` is `PLANNED` becomes `VOIDED`. The show's `version` increments, as does the `version` of every division and class the closure touched.

`APPROVE` moves the show `SUBMITTED → APPROVED` and is the only decision that requires the class list to still be substantive; a show with no class beneath its divisions cannot be approved, and the refusal is again `ERR_CLASS_LIST_INCOMPLETE`. Approval freezes the money: for every division of the show, `division_allotment_cents` is written, and for every class beneath those divisions, `class_purse_cents` is written, both by the allocation arithmetic described in §3.2. The show's `version` increments. `APPROVED` and `DENIED` are terminal licence states.

Approval also locks the structure. Divisions and classes may only be created while the show's `license_status` is `DRAFT` or `RETURNED_FOR_CORRECTION`; once the licence is `SUBMITTED`, `APPROVED` or `DENIED`, a creation attempt is refused with `ERR_SHOW_LICENSE_LOCKED`. Conversely, opening a class for entries, submitting an entry and calling a class into the ring all require `license_status` to be exactly `APPROVED`, and each refuses with `ERR_SHOW_LICENSE_NOT_APPROVED` otherwise.

### 3.2. Divisions, Classes and How the Purse Divides

Divisions carve the show into competitive bands. A `ShowSecretary` adds one with a `name` such as "Junior Jumper", a `discipline` from `HUNTER`, `JUMPER`, `EQUITATION` or `DRESSAGE`, and an `age_group` from `JUNIOR`, `AMATEUR`, `OPEN` or `PONY`. The division fixes an inclusive fence-height band with `min_jump_height_cm` and `max_jump_height_cm`, neither negative and the upper bound at least equal to the lower. It claims a slice of the show's purse with `division_share_bp`, a basis-point figure between 0 and 10000 inclusive. And it declares with `jumpoff_enabled` whether its classes run a jump-off; the flag defaults to false and only affects duration estimation for jumper classes. A new division is created with `status` of `ACTIVE` and `division_allotment_cents` of 0, and the show's `division_share_bp_total` and `version` are both recomputed on creation. If adding the division would push the show's `ACTIVE` divisions' shares above 10000 basis points in total, the creation is refused with `ERR_DIVISION_SHARE_OVERSUBSCRIBED`. The only other value `status` takes is `CLOSED`, reached when the show's licence is denied.

Classes hang beneath divisions. Creating one requires a `class_number` — the prize-list number, at least 1, and unique across every class of the same show, with a collision reported as `ERR_CLASS_NUMBER_DUPLICATE` — a printed `name`, a `jump_height_cm`, a per-horse `entry_fee_cents`, a `class_share_bp` between 0 and 10000 inclusive claiming a slice of the division's allotment, and a `max_entries` ceiling of at least 1. The fence height must lie inside the division's band, inclusive at both ends: a height equal to `min_jump_height_cm` or equal to `max_jump_height_cm` is acceptable, anything below the former or above the latter is `ERR_JUMP_HEIGHT_OUT_OF_RANGE`.

A class may optionally name, through `qualifier_for_class_id`, the championship class it qualifies riders for; the field defaults to null. The named class must belong to the same show, and following the chain of `qualifier_for_class_id` references transitively from the new class must never arrive back at the new class itself. A reference outside the show, or one that would close a cycle, is refused with `ERR_QUALIFIER_CYCLE`. The chain is therefore a directed acyclic graph within one show.

Two counters on a class track its field, and their populations differ. `entry_count` is the number of class entries on the class whose `status` is `ENTERED`, `CONFIRMED`, `COMPLETED` or `DISQUALIFIED` — scratched rows drop out of it — and it is `entry_count` that `max_entries` caps. `confirmed_entry_count` is the narrower number of class entries whose `status` is `CONFIRMED` or `COMPLETED`; a starter that has gone in the ring still counts. That second counter is the one that drives point eligibility and the national multiplier tier, so a class does not lose its multiplier tier merely because its confirmed starters have since been judged.

A newly created class has `status` of `PLANNED`, `entry_count` and `confirmed_entry_count` of 0, `class_purse_cents` and `awarded_prize_cents` of 0, `placed_count` of 0, `point_eligible` false, and both `estimated_minutes` and `actual_minutes` null. Creation increments the parent division's `version`.

Opening a class for entries moves it `PLANNED → OPEN`. Only a class in `PLANNED` may be opened — otherwise `ERR_CLASS_NOT_PLANNED` — the owning show's licence must be `APPROVED`, and the owning division's `status` must be `ACTIVE`. Opening recomputes `class_purse_cents` and increments the class's `version`. The full set of states a class visits is `PLANNED`, `OPEN`, `SCHEDULED`, `IN_PROGRESS`, `JUDGED`, `RESULTS_POSTED`, `POINTS_SUBMITTED` and `VOIDED`, and `VOIDED` is terminal.

**The purse waterfall.** Prize money descends in two rounding steps whose order is fixed. A division's `division_allotment_cents` is the show's `prize_money_pool_cents` multiplied by that division's `division_share_bp`, divided by 10000, rounded half up to whole cents. A class's `class_purse_cents` is then its division's already-rounded `division_allotment_cents` multiplied by the class's `class_share_bp`, divided by 10000, rounded half up to whole cents. The class figure is computed from the rounded division figure, never from the unrounded product.

Five ribbons share a class purse, in basis points of that purse: first place takes 4000, second 2500, third 1600, fourth 1100 and fifth 800 — a table that sums to exactly 10000. The order of operations when the purse is actually paid out is pinned. Let the number of paying places be the smaller of 5 and the class's `placed_count`. Working upward from first place to that last paying place, each place's cents figure is computed independently as `class_purse_cents` multiplied by that place's basis-point share, divided by 10000, rounded half up to whole cents. Only after all of those individual figures exist are they summed. Summing the exact unrounded shares and rounding once at the end is explicitly not the specified order.

Residual reconciliation applies in exactly one situation: when all five ribbons were filled. In that case the difference between `class_purse_cents` and the sum of the five rounded figures — which may be negative — is added to first place's figure, and the class's `awarded_prize_cents` becomes exactly `class_purse_cents`. When fewer than five places were filled, the unfilled places' shares are not redistributed to anyone: `awarded_prize_cents` is simply the sum of the filled places' figures and is strictly less than `class_purse_cents`. Each placed class entry's `prize_cents` is the figure for its own placing; entries with a null placing, entries that were scratched, and entries that were disqualified all carry `prize_cents` of 0.

### 3.3. Grounds, Footing and Emergency Coverage

Rings are the show's physical capacity. A `ShowSecretary` adds one with a `name` such as "Grand Prix Field" and a `surface_type` of `SAND_FIBER`, `GRASS` or `CLAY`. Three optional figures shape how the ring behaves: `footing_condition_score`, a seed value from 0 to 100 inclusive that defaults to 100; `turnover_buffer_minutes`, the drag-and-reset time required between consecutive occupancies, defaulting to 10 and never negative; and `warmup_capacity_horses`, the maximum number of horses permitted in the ring's warm-up arena at one time, defaulting to 12 and at least 1. A new ring has `status` of `AVAILABLE`, `scheduled_minutes_total` of 0 and `slot_count` of 0, and its creation increments the parent show's `version`. `AVAILABLE` and `MAINTENANCE_HOLD` are the only two ring postures, and neither is terminal.

Footing work is recorded by a `GroundsManager` against a specific window: a `start_utc`, a `duration_minutes` length of at least one minute, and the `new_footing_condition_score` the surface reached after the pass. Every footing pass, whatever the resulting score, does three things: it synthesises a maintenance occupancy on the ring for the requested window with the requested length, it rewrites `footing_condition_score` to `new_footing_condition_score`, and it recomputes the ring's `scheduled_minutes_total`, `slot_count` and the `order_index` of every occupancy on the ring, incrementing the ring's `version`. The hold window must lie inside the show's competition window; a window not fully contained between `start_utc` and `end_utc` of the show is refused with `ERR_SLOT_OUTSIDE_SHOW_WINDOW`.

What differs is the posture the ring lands in, and the threshold is a footing score of 60. A pass that leaves the surface at 60 or above from an `AVAILABLE` ring leaves the ring `AVAILABLE` — a same-state transition — and the requested hold window is checked against the ring's existing occupancies under the overlap geometry of §3.5; a collision is `ERR_RING_SLOT_OVERLAP`. A pass that leaves the surface at 60 or above from a ring already on `MAINTENANCE_HOLD` returns it `MAINTENANCE_HOLD → AVAILABLE`. Slots cancelled during the hold are not resurrected by that return; they must be booked again from scratch. A pass on a ring already on `MAINTENANCE_HOLD` that leaves the surface below 60 is refused with `ERR_RING_NOT_AVAILABLE`, as the ring is already in the wrong posture for that request.

**The footing cascade.** A pass that drops an `AVAILABLE` ring's surface below 60 fires the deepest cascade in the system, because an unsafe surface pre-empts whatever was booked on it. The maintenance occupancy is created for the hold window *without* the overlap check — deliberately, since the point is to displace existing bookings. Then, in order: the ring moves `AVAILABLE → MAINTENANCE_HOLD`; every class occupancy on that ring whose `status` is `SCHEDULED` moves `SCHEDULED → CANCELLED`; for each occupancy so cancelled, its class reverts `SCHEDULED → OPEN` and that class's `estimated_minutes` is set back to null; and for each occupancy so cancelled, every official assignment on it whose `status` is `ACTIVE` moves `ACTIVE → RELEASED`, with that official's `assigned_minutes` decremented by exactly the whole minutes from the released occupancy's `warmup_start_utc` to its `end_utc`. Every one of those resources — ring, occupancies, classes, assignments and officials — has its `version` incremented and its `updated_at` refreshed. `RELEASED` is terminal for an assignment.

**Coverage.** Emergency veterinary and farrier availability is booked as coverage windows by a `GroundsManager`, each with a `coverage_type` of `VETERINARIAN` or `FARRIER`, a `provider_name`, and an inclusive window from `start_utc` to `end_utc`. A new window has `status` of `SCHEDULED`. The distinction between the two types is consequential: active veterinary coverage is a precondition for calling any class into a ring, while farrier coverage is recorded for the record and gates nothing.

A provider checks in by activating the window, moving it `SCHEDULED → ACTIVE` and incrementing its `version`. Activation is only permitted from `SCHEDULED`; a second activation is refused with `ERR_COVERAGE_SHIFT_NOT_SCHEDULED`. And it is only permitted once the logical clock has reached one hour before the window opens — that is, at or after the window's `start_utc` minus 60 minutes. Earlier than that, the answer is `ERR_COVERAGE_CHECKIN_TOO_EARLY`. `SCHEDULED` and `ACTIVE` are the only two coverage states and neither is terminal.

### 3.4. Registries: Officials, Riders and Horses

The federation maintains three registries, all written by a `FederationOfficer`.

An official is registered with a `federation_official_id` licence number, a `full_name`, a non-empty `license_roles` array whose members are drawn from `JUDGE`, `STEWARD` and `TECHNICAL_DELEGATE`, a `license_level` grade from 1 to 4 inclusive, a non-empty `licensed_disciplines` array whose members are drawn from `HUNTER`, `JUMPER`, `EQUITATION` and `DRESSAGE`, and a `license_expires_on` instant. An optional `affiliated_trainer_name` records the barn the official is commercially tied to and defaults to null; it exists solely to drive the conflict-of-interest rule of §3.6. A newly registered official has `assigned_minutes` of 0.

A rider is registered with a `federation_member_number`, a `full_name`, a `membership_expires_on` instant and a `trainer_name` of record. Membership is not stored as a settled state: `membership_status` is re-derived on every read as `ACTIVE` when the logical clock is strictly before `membership_expires_on` and `LAPSED` otherwise. A new rider's `national_points_total` and `regional_points_total` are both 0.

A horse is registered with a `federation_registration_number`, its registered `name`, an `owner_name` and the `coggins_drawn_on` instant at which its EIA blood sample was taken. The service derives `coggins_expires_on` as `coggins_drawn_on` plus 365 days, and sets `eligibility_status` to `ELIGIBLE`. The only other eligibility value is `SUSPENDED`, reached only by a substantiated positive compliance finding.

### 3.5. Entry Processing: Two Independent Dimensions

An entry pairs one rider with one horse at one show, and it advances along two dimensions that do not wait for each other. `verification_status` is the paperwork dimension and takes `RECEIVED`, `VERIFIED`, `ACCEPTED` or `WITHDRAWN`. `settlement_status` is the money dimension and takes `UNBILLED`, `INVOICED`, `PAID` or `REFUNDED`. An entry may be invoiced while still `RECEIVED`, and it may be verified while still `UNBILLED`. `WITHDRAWN` and `REFUNDED` are the terminal values of their respective dimensions.

An `Exhibitor` submits an entry to a licensed show, naming the `rider_id` competing and the `horse_id` competing, with an optional `requested_stall_count` defaulting to 0 and never negative. The acting exhibitor must be the entering rider — the submitted `rider_id` and the ownership check both resolve against `X-User-ID`, and a mismatch is `ERR_ENTRY_NOT_OWNED`. The show's licence must be `APPROVED`. And the logical clock must be strictly before the show's `entry_close_utc`; at or after that instant the answer is `ERR_ENTRY_WINDOW_CLOSED`. A new entry has `verification_status` of `RECEIVED`, `settlement_status` of `UNBILLED`, `assigned_stall_count` of 0, all five settlement figures — `class_fee_cents_total`, `stall_fee_cents`, `preliminary_subtotal_cents`, `office_fee_cents` and `total_due_cents` — at 0, and `refunded_cents` at 0.

**Verification.** A `ShowSecretary` verifies an entry, moving `RECEIVED → VERIFIED` and incrementing the entry's `version`. Only an entry in `RECEIVED` may be verified; otherwise `ERR_ENTRY_NOT_RECEIVED`. Three substantive checks then run in a fixed order. The rider's `membership_status` must be `ACTIVE` at the logical clock, failing which the answer is `ERR_RIDER_MEMBERSHIP_LAPSED`. The horse's `coggins_expires_on` must be at or after the show's `start_utc` — equality is acceptable — failing which `ERR_COGGINS_EXPIRED`. And the horse's `eligibility_status` must be `ELIGIBLE`, failing which `ERR_HORSE_SUSPENDED`. The Coggins and eligibility checks are not unique to verification: both are re-run whenever the entry is added to a class, with the same two error codes.

**Acceptance.** Accepting a verified entry moves `VERIFIED → ACCEPTED` and is where stalls are actually committed. Only an entry in `VERIFIED` may be accepted; otherwise `ERR_ENTRY_NOT_VERIFIED`. The entry's `requested_stall_count` must not exceed the show's current `available_stall_count`; only a strictly greater request is refused, and the refusal is `ERR_STALL_CAPACITY_EXCEEDED`. On success the entry's `assigned_stall_count` is set to its `requested_stall_count`, the show's `reserved_stall_count` and `available_stall_count` are recomputed per the stall ledger of §2.10, and both the entry's and the show's `version` increment. Acceptance also completes the confirmation join described below.

**Invoicing.** Freezing the invoice moves `UNBILLED → INVOICED` and writes all five settlement figures; a second attempt is refused with `ERR_ENTRY_ALREADY_INVOICED`, and an attempt on a withdrawn entry is refused with `ERR_ENTRY_ALREADY_TERMINAL`. The arithmetic is a tiered lookup with a deliberately pinned evaluation order. First, `class_fee_cents_total` is the sum of `entry_fee_cents` over the classes named by this entry's class entries whose `status` is `ENTERED`, `CONFIRMED`, `COMPLETED` or `DISQUALIFIED`; scratched rows are excluded. Second, `stall_fee_cents` is the entry's `requested_stall_count` multiplied by the show's `stall_fee_cents` — the *requested* count, never the assigned one, which is why the invoice is entirely independent of where the verification dimension has got to. Third, `preliminary_subtotal_cents` is `class_fee_cents_total` plus `stall_fee_cents`.

The office fee is described in the prize list as "waived on large invoices", which sounds like a rule about the total. It is not. The tier is keyed on `preliminary_subtotal_cents` — the pre-fee figure — and evaluated exactly once. When `preliminary_subtotal_cents` is at least 100000 cents, `office_fee_cents` is 0. When it is at least 50000 cents but below 100000, `office_fee_cents` is 2500. Below 50000 cents, `office_fee_cents` is 5000. Finally `total_due_cents` is `preliminary_subtotal_cents` plus `office_fee_cents`, and there is no re-evaluation: a subtotal of 97500 cents attracts a 2500-cent office fee and a total of 100000 cents, even though 100000 would itself have qualified for the waiver. Invoicing increments the entry's `version`.

**Payment.** An `Exhibitor` who owns the entry pays it in full by supplying `amount_cents`, moving `INVOICED → PAID`. An entry not in `INVOICED` is refused with `ERR_ENTRY_NOT_INVOICED`, and an `amount_cents` that is not exactly equal to `total_due_cents` — short or over — is refused with `ERR_PAYMENT_AMOUNT_MISMATCH`. Payment increments the entry's `version` and, like acceptance, may complete the confirmation join.

**The confirmation join.** A class entry starts life `ENTERED` and only reaches `CONFIRMED` when *both* entry dimensions have landed: `verification_status` of `ACCEPTED` and `settlement_status` of `PAID`. Neither dimension alone confirms anything. Whichever of acceptance or payment completes the pair sweeps this entry's class entries whose `status` is `ENTERED`, moves each `ENTERED → CONFIRMED`, and recomputes the affected classes' `confirmed_entry_count` and `point_eligible`. Each swept class entry's `version` increments, as does each affected class's.

**Withdrawal.** An `Exhibitor` who owns the entry may withdraw it from `RECEIVED`, `VERIFIED` or `ACCEPTED`; an entry already `WITHDRAWN` is refused with `ERR_ENTRY_ALREADY_TERMINAL`. The same code guards two further situations. A withdrawal is refused when any class entry of the entry has `status` of `DISQUALIFIED`, and it is refused when any class entry of the entry has `status` of `COMPLETED` on a class whose own `status` has already reached `RESULTS_POSTED`, `POINTS_SUBMITTED` or `VOIDED`. Notably, a `COMPLETED` class entry on a class that is merely `JUDGED` does *not* block withdrawal — which is precisely how a placed-but-refunded row can come to exist, and why posting results carries the unpaid-placed-entry check of §3.8.

Withdrawal is the compensating action for acceptance and, when money has changed hands, for payment. `verification_status` becomes `WITHDRAWN`; `assigned_stall_count` returns to 0 and the show's `reserved_stall_count` and `available_stall_count` are recomputed, restoring `reserved_stall_count` to its exact pre-acceptance value; every class entry of the entry whose `status` is `ENTERED` or `CONFIRMED` moves to `SCRATCHED`, with each affected class's `entry_count`, `confirmed_entry_count` and `point_eligible` recomputed. If `settlement_status` was `PAID`, it moves `PAID → REFUNDED` and `refunded_cents` is set to `total_due_cents`. The entry's and the show's `version` both increment, as do those of every class entry and class touched.

**Entering classes.** An `Exhibitor` who owns the entry adds it to a specific class by naming the `entry_id` and the `class_id`. The class must be `OPEN`, otherwise `ERR_CLASS_NOT_OPEN`. The logical clock must still be strictly before the show's `entry_close_utc`, otherwise `ERR_ENTRY_WINDOW_CLOSED`. The horse's `coggins_expires_on` must still be at or after the show's `start_utc` and its `eligibility_status` must still be `ELIGIBLE`, failing which `ERR_COGGINS_EXPIRED` and `ERR_HORSE_SUSPENDED` respectively. The class's `entry_count` must be strictly less than its `max_entries`; a full class is `ERR_CLASS_FULL`. And no existing class entry may already pair the same entry with the same class with a `status` of `ENTERED`, `CONFIRMED`, `COMPLETED` or `DISQUALIFIED` — a duplicate is `ERR_DUPLICATE_CLASS_ENTRY`, while a previously `SCRATCHED` pairing does not block a fresh one.

A new class entry has `status` of `ENTERED`, or `CONFIRMED` immediately when the parent entry is already both `ACCEPTED` and `PAID`. Its `placing` and `round_seconds` are null, and `prize_cents`, `points_national` and `points_regional` are all 0. Creation recomputes the class's `entry_count`, `confirmed_entry_count` and `point_eligible`, and increments the class's `version`. `COMPLETED`, `DISQUALIFIED` and `SCRATCHED` are the terminal class-entry states.

### 3.6. Ring Scheduling and Officiating

A `RingMaster` books a class into a ring by naming the `ring_id` whose time is being taken, the `class_id` being booked, the `start_utc` at which it will begin, and the `expected_ring_version` of §2.7. Only a class in `OPEN` may be booked, otherwise `ERR_CLASS_NOT_OPEN`; and a class that already holds an occupancy on any ring with `status` of `SCHEDULED`, `RUNNING` or `COMPLETED` may not be booked a second time, which is `ERR_CLASS_ALREADY_SCHEDULED`.

Booking writes an occupancy — a ring slot — whose `slot_type` is `CLASS`, whose `class_id` names the booked class, and whose `status` is `SCHEDULED`. Its `duration_minutes` is copied from the class's freshly computed `estimated_minutes`; its `end_utc` is its `start_utc` advanced by `duration_minutes`, and that upper bound is half-open, so the ring is free again at `end_utc`; and its `warmup_start_utc` is its `start_utc` moved back by 30 minutes, marking the beginning of the supervised warm-up window. Warm-up windows play no part in ring collision detection — they matter only for officials' occupancy, per the geometry below. Maintenance occupancies synthesised by footing work carry `slot_type` of `MAINTENANCE`, a null `class_id`, and a `duration_minutes` equal to the requested hold length; a class occupancy always has a non-null `class_id`. Occupancies visit `SCHEDULED`, `RUNNING`, `COMPLETED` and `CANCELLED`, with the last two terminal.

The booked window must be fully contained inside the show's competition window: the show's `start_utc` must be at or before the occupancy's `start_utc`, and the occupancy's `end_utc` must be at or before the show's `end_utc`. Anything else is `ERR_SLOT_OUTSIDE_SHOW_WINDOW`.

**Ring overlap geometry.** A candidate occupancy is compared against every existing occupancy on the same ring whose `status` is `SCHEDULED` or `RUNNING`; cancelled and completed occupancies never block. The comparison is on half-open intervals widened symmetrically by the ring's `turnover_buffer_minutes`. The candidate collides with an existing occupancy when the candidate's `start_utc` is strictly earlier than that occupancy's `end_utc` advanced by `turnover_buffer_minutes`, *and* that occupancy's `start_utc` is strictly earlier than the candidate's `end_utc` advanced by `turnover_buffer_minutes`. Because both comparisons are strict, a candidate that begins exactly at an existing occupancy's `end_utc` plus the buffer does not collide. Any collision is `ERR_RING_SLOT_OVERLAP`.

**Running order.** After every insertion — a class booking or a maintenance hold — the ring's running order is recomputed across the whole ring. The occupancies that count are those whose `status` is `SCHEDULED`, `RUNNING` or `COMPLETED`; they are sorted by `start_utc` ascending, with `created_at` ascending as the sole tie-break (`id` is never consulted), and each is assigned a 1-based `order_index` equal to its position in that sorted list. The ring's `scheduled_minutes_total` becomes the sum, over those same occupancies, of the whole minutes from each one's `start_utc` to its `end_utc`, and `slot_count` becomes their count. Booking increments both the ring's and the class's `version`, and moves the class `OPEN → SCHEDULED`.

**Duration estimation.** How long a class will occupy its ring is computed from four inputs and a branch on discipline, and the arithmetic runs in a fixed sequence. Start from a base round time in seconds determined by the division's `discipline`: 90 seconds for `HUNTER`, 75 for `JUMPER`, 100 for `EQUITATION` and 300 for `DRESSAGE`. Next compute a height factor as 1 plus the greater of zero and the amount by which the class's `jump_height_cm` exceeds 100 centimetres, that excess divided by 200 — so a 100-centimetre class has a factor of exactly 1, a 140-centimetre class a factor of 1.2, and a class below 100 centimetres also exactly 1.

Let the entry count for the estimate be the number of class entries selected by the variant in play (below). The number of scheduled rounds equals that count. A jump-off adds rounds only when the division's `jumpoff_enabled` is true *and* the division's `discipline` is `JUMPER`; in that case the jump-off rounds are the smaller of 8 and the entry count multiplied by 0.30 rounded up to a whole number. In every other case there are zero jump-off rounds.

Course walk time is the greater of 10 minutes and the entry count divided by ten, rounded up to a whole number, then multiplied by 5 minutes. Ride time in minutes is obtained by multiplying the total round count — scheduled rounds plus jump-off rounds — by the base round seconds, multiplying that product by the height factor, dividing by 60, and rounding the result up to a whole minute. The single rounding-up happens exactly once, at the end, after both multiplications; rounding each round to whole minutes and then summing is not the specified order and produces a different answer. Finally, `estimated_minutes` is ride time plus course walk time plus the ring's `turnover_buffer_minutes`.

Two variants of the entry count exist, and they differ only in which class entries they count. The *projected* variant counts class entries whose `status` is `ENTERED` or `CONFIRMED`, so it includes horses whose parent entry has not yet been accepted or paid. The *confirmed-only* variant counts class entries whose `status` is exactly `CONFIRMED`. Rows whose `status` is `SCRATCHED` or `DISQUALIFIED` are excluded from both. Because confirmation requires both entry dimensions, the confirmed-only population is always a subset of the projected one, and the two variants therefore report different minute counts over identical stored data. Booking a class into a ring writes the *projected* variant into `estimated_minutes`.

The show's schedule projection read reports both. For every class of the show that currently holds an occupancy whose `status` is `SCHEDULED` or `RUNNING`, it recomputes both variants against that occupancy's ring and returns `show_id`, the aggregate `projected_total_minutes` from the projected variant, the aggregate `confirmed_only_total_minutes` from the confirmed-only variant, `projected_drift_minutes` as `projected_total_minutes` minus `confirmed_only_total_minutes`, and a `class_projections` array carrying the per-class figures. The read computes and stores nothing.

**Carding officials.** A `ShowSecretary` cards an official onto an occupancy by naming the `official_id`, the `slot_id` and the `official_role` chair being filled — `JUDGE`, `STEWARD` or `TECHNICAL_DELEGATE`. A new assignment has `status` of `ACTIVE`, and the official's `assigned_minutes` is increased by the whole minutes from the occupancy's `warmup_start_utc` to its `end_utc`; the official's `version` increments.

Four checks guard the card, and they run in this order. First, licence sufficiency: the requested `official_role` must be a member of the official's `license_roles`; the discipline of the booked class's division must be a member of the official's `licensed_disciplines`; the official's `license_level` must be at least the minimum the show's `competition_level` demands — grade 1 for `LOCAL`, grade 2 for `REGIONAL`, grade 3 for `NATIONAL` and grade 4 for `PREMIER`; and the occupancy's `start_utc` must fall strictly before the official's `license_expires_on`, so an assignment beginning exactly at expiry is refused. Any of those four failures is `ERR_OFFICIAL_LICENSE_INSUFFICIENT`.

Second, conflict of interest. The official's `affiliated_trainer_name` must not equal the `trainer_name` of any rider holding a class entry with `status` of `ENTERED` or `CONFIRMED` in the occupancy's class. A match is `ERR_OFFICIAL_CONFLICT_OF_INTEREST`.

Third, the official's own time geometry, which is deliberately stricter than the ring's in two ways. The official's occupancy of an assignment runs on a *closed* interval from the assigned occupancy's `warmup_start_utc` to its `end_utc` — the supervised warm-up window counts as occupied time. The candidate is compared only against other `ACTIVE` assignments of the same official that sit on a *different* occupancy; a second chair on the very same occupancy is exempt from this check, because the official is already standing in that ring, and the duties clash it creates is caught instead by the segregation-of-duties rule at card time. Only assignments whose occupancy has `status` of `SCHEDULED` or `RUNNING` are considered; released assignments and cancelled or completed occupancies are ignored. A required travel gap widens the comparison: zero minutes when the two occupancies are on the same ring, and 20 minutes when they are on different rings. The candidate collides with an existing assignment when the candidate's `warmup_start_utc` is at or before the existing occupancy's `end_utc` advanced by the required gap, *and* the existing occupancy's `warmup_start_utc` is at or before the candidate's `end_utc` advanced by the required gap. Both comparisons are non-strict, so intervals that merely touch at their endpoints do collide. Any collision is `ERR_OFFICIAL_TIME_CONFLICT`.

Fourth, the daily load ceiling. The official's current `assigned_minutes` plus the whole minutes from the candidate occupancy's `warmup_start_utc` to its `end_utc` must not exceed 480 minutes — eight hours of carded duty per official. Exceeding it is `ERR_OFFICIAL_LOAD_EXCEEDED`.

### 3.7. Calling the Class and Recording the Card

Calling a class into the ring is the moment every readiness condition converges, and a `RingMaster` performs it against a specific occupancy. Only an occupancy whose `status` is `SCHEDULED` may be called, and only one whose `slot_type` is `CLASS`; a maintenance occupancy or an occupancy in any other status is refused with `ERR_SLOT_NOT_SCHEDULED`. The ring's `status` must be `AVAILABLE`, otherwise `ERR_RING_NOT_AVAILABLE`. The show's licence must be `APPROVED`, otherwise `ERR_SHOW_LICENSE_NOT_APPROVED`.

Then the safety gates, in order. The ring's `footing_condition_score` must be at least 60, otherwise `ERR_FOOTING_UNSAFE` — the same threshold that decides whether a footing pass puts the ring on hold, checked again here because a hold can be lifted while the surface is still marginal. There must exist a coverage window of the same show whose `coverage_type` is `VETERINARIAN` and whose `status` is `ACTIVE`, with its `start_utc` at or before the occupancy's `start_utc` and its `end_utc` at or after the occupancy's `end_utc` — the coverage must span the whole occupancy, and a `SCHEDULED` window whose provider has not checked in does not count. A gap is `ERR_VET_COVERAGE_MISSING`.

Next the required-officials matrix, which is keyed on the show's `competition_level`. A `LOCAL` show requires 1 judge and 1 steward and no technical delegate. A `REGIONAL` show requires 2 judges and 1 steward and no technical delegate. A `NATIONAL` show requires 2 judges, 1 steward and 1 technical delegate. A `PREMIER` show requires 3 judges, 2 stewards and 1 technical delegate. For each chair the matrix demands in a positive quantity, the occupancy must carry at least that many *distinct* officials holding an `ACTIVE` assignment in that chair; chairs the matrix sets to zero are not checked at all. A shortfall is `ERR_OFFICIALS_REQUIREMENT_UNMET`.

Finally the welfare gate: the show's `welfare_strike_count` must be strictly below 2. Once a show has accumulated two substantiated welfare strikes, competition may not continue until the federation clears the show, and further calls are refused with `ERR_WELFARE_STRIKE_LIMIT`.

On success the occupancy moves `SCHEDULED → RUNNING` and its class moves `SCHEDULED → IN_PROGRESS`; both `version` counters increment.

**The judge's card.** A `Judge` records results for a class in `IN_PROGRESS`; any other class status is `ERR_CLASS_NOT_IN_PROGRESS`. The card carries `placings` — a list pairing each ribboned class entry with the position it took and the time it went — and `actual_minutes`, the whole minutes the class actually occupied the ring.

Four further checks apply. The class's `entry_count` must be at least 1; a class with nothing in it is `ERR_NO_ENTRIES_TO_JUDGE`. The acting judge, resolved from `X-User-ID`, must hold an assignment with `status` of `ACTIVE` and `official_role` of `JUDGE` on this class's `RUNNING` occupancy; if not, `ERR_JUDGE_NOT_ASSIGNED`. Segregation of duties then forbids the same person from also holding an `ACTIVE` assignment with `official_role` of `STEWARD` on that same occupancy; if they do, the card is refused with `ERR_SEGREGATION_OF_DUTIES`. And the placings themselves must be well-formed: the positions supplied must be distinct integers forming a contiguous run starting at 1, the number of positions may not exceed the smaller of 5 and the count of this class's class entries whose `status` is `CONFIRMED`, and every class entry named in the card must belong to this class and be `CONFIRMED`. Any violation is `ERR_INVALID_PLACINGS`.

Recording the card does five things. Every class entry named in `placings` moves `CONFIRMED → COMPLETED` with its `placing` and its `round_seconds` written from the card. Every class entry of the class that was `CONFIRMED` but *not* named in the card also moves to `COMPLETED`, but with `placing` left null and `round_seconds` unrecorded — no confirmed starter is left behind in `CONFIRMED`. The class moves `IN_PROGRESS → JUDGED` with `actual_minutes` written from the card and `placed_count` recomputed as the number of its class entries that have a non-null `placing` and a `status` of `COMPLETED`. The class's `RUNNING` occupancy moves `RUNNING → COMPLETED`, and the ring's `scheduled_minutes_total` is recomputed. The class's and the occupancy's `version` counters both increment.

### 3.8. Posting the Purse and Submitting to Standings

Posting official results is the `ShowSecretary`'s act, and it moves the class `JUDGED → RESULTS_POSTED`. A class not in `JUDGED` is refused with `ERR_CLASS_NOT_JUDGED`. Two fiscal checks then run. Every class entry on the class carrying a non-null `placing` must belong to an entry whose `settlement_status` is `PAID`; a placed entry that was refunded after judging, or was never paid, blocks the posting with `ERR_UNPAID_PLACED_ENTRY` (HTTP 402). And the show's current `allocated_prize_cents` plus the purse about to be awarded must not exceed `prize_money_pool_cents`; otherwise `ERR_PRIZE_POOL_EXCEEDED`.

On success, each placed class entry's `prize_cents` is written by the ribbon waterfall of §3.2 — rounded per place, ascending, then summed, with the residual folded into first place only when all five ribbons were filled. The class's `awarded_prize_cents` becomes the sum of the figures written. The show's `allocated_prize_cents` and `unallocated_prize_cents` are recomputed per the prize ledger. The class's `point_eligible` is recomputed as true when its `confirmed_entry_count` is at least 3 and false otherwise. Both the class's and the show's `version` increment.

Voiding posted results is the compensating action. It moves the class `RESULTS_POSTED → VOIDED`, and only from `RESULTS_POSTED` — otherwise `ERR_CLASS_RESULTS_NOT_POSTED`. It is additionally refused once a standings body has taken the class's submission seriously: if any standings submission for this class has a `status` of `NATIONAL_ACCEPTED`, `REGIONAL_ACCEPTED` or `RECORDED`, the void fails with `ERR_SUBMISSION_ALREADY_FINALIZED`. When it succeeds, every class entry on the class has `prize_cents` reset to 0, the class's `awarded_prize_cents` becomes 0, and the show's `allocated_prize_cents` and `unallocated_prize_cents` are recomputed, returning the released purse to the unallocated side with zero drift. The class's and the show's `version` increment. `VOIDED` is terminal for a class.

**Raising a submission.** A `ShowSecretary` raises a standings submission for a class in `RESULTS_POSTED`, supplying `expected_class_version` per §2.7. A class not in `RESULTS_POSTED` is refused with `ERR_CLASS_RESULTS_NOT_POSTED`, and a class whose `point_eligible` is false — that is, whose `confirmed_entry_count` is below 3 — is refused with `ERR_CLASS_NOT_POINT_ELIGIBLE`. The submission is created with `status` of `PREPARED`, `submitted_by_user_id` set to the raising secretary's `X-User-ID`, `national_body_reference` and `regional_body_reference` both null, and `national_points_total` and `regional_points_total` both 0. The class moves `RESULTS_POSTED → POINTS_SUBMITTED` and its `version` increments.

**The two-body saga.** A submission is acknowledged one body at a time by a `FederationOfficer`, who supplies the `standings_body` acknowledging — `NATIONAL` or `REGIONAL` — the `outcome` — `ACCEPTED` or `REJECTED` — and, on acceptance, an optional `body_reference` string. The two legs are independent forks that join at `RECORDED`. From `PREPARED`, a national acceptance moves the submission `PREPARED → NATIONAL_ACCEPTED` and a regional acceptance moves it `PREPARED → REGIONAL_ACCEPTED`. From `NATIONAL_ACCEPTED`, a regional acceptance moves it `NATIONAL_ACCEPTED → RECORDED`; from `REGIONAL_ACCEPTED`, a national acceptance moves it `REGIONAL_ACCEPTED → RECORDED`. Whichever leg lands second carries exactly the same side effects it would have carried had it landed first. Any acknowledgement attempted against a submission already `RECORDED`, `REJECTED` or `RETRACTED` is refused with `ERR_SUBMISSION_ALREADY_FINALIZED`. `RECORDED`, `REJECTED` and `RETRACTED` are terminal.

An accepted **national** leg writes `points_national` on every class entry of the class whose `status` is `COMPLETED`, sets the submission's `national_points_total` to the sum of those values, stores the supplied `body_reference` as `national_body_reference`, and credits each placed class entry's rider by adding that class entry's `points_national` to the rider's `national_points_total`. An accepted **regional** leg writes `points_regional` on the same population, sets the submission's `regional_points_total` to the sum of those values, stores the supplied `body_reference` as `regional_body_reference`, and adds each placed class entry's `points_regional` to its rider's `regional_points_total`. Either way the submission's `version` increments.

**The two scoring scales.** Only class entries with a `status` of `COMPLETED` and a non-null `placing` score anything; rows that are `DISQUALIFIED` or `SCRATCHED`, and rows whose `placing` is null, score zero on both scales.

The national scale awards through fifth place from a fixed table: 10 points for first, 6 for second, 4 for third, 3 for fourth and 2 for fifth. That whole table is then scaled by a multiplier chosen from the class's `confirmed_entry_count`: when it is at least 25 the multiplier is 2.0; otherwise when it is at least 10 the multiplier is 1.5; otherwise when it is at least 3 the multiplier is 1.0; and below 3 the multiplier is 0.0. A class entry's `points_national` is its table value multiplied by that multiplier, rounded half up to one decimal place. There is no per-show cap on national points.

The regional scale is flatter and capped. It awards only through third place — 8 points for first, 5 for second, 3 for third — and any placing beyond third scores zero. There is no entry-count multiplier. A per-show ceiling of 20 regional points then applies per rider: the class entries of the same show belonging to the same rider are processed in ascending order of the class's `class_number`, with the class entry's `created_at` ascending as the tie-break, and each row's `points_regional` is the smaller of its raw table value and whatever headroom remains — that is, the greater of zero and 20 minus the regional points already credited to that rider for that show. "Already credited" sums `points_regional` over that rider's class entries at the same show whose submission has a `status` of `REGIONAL_ACCEPTED` or `RECORDED`. Regional points are whole numbers.

The two scales genuinely disagree for identical results, which is the point of running both. A first place in a three-entry class scores 10.0 nationally and 8 regionally; a fourth place in the same class scores 3.0 nationally and 0 regionally.

A rider's standings read recomputes both totals from accepted submissions without storing anything, optionally scoped by `show_id`, and returns `rider_id`, `national_points_total`, `regional_points_total`, `national_class_count` — the number of classes contributing national points — and `regional_capped`, a boolean reporting whether the per-show regional ceiling bound.

**Rejection and compensation.** A `REJECTED` outcome may arrive while the submission is `PREPARED`, `NATIONAL_ACCEPTED` or `REGIONAL_ACCEPTED`, and it moves the submission to `REJECTED` from any of the three. It compensates whatever had already been credited: for each leg already accepted, the credited `points_national` or `points_regional` figures are subtracted from the corresponding rider totals and those class-entry fields are reset to 0. The submission's own `national_points_total` and `regional_points_total` both become 0. The class then reverts `POINTS_SUBMITTED → RESULTS_POSTED`, which is what allows a corrected submission to be raised against it. The submission's and the class's `version` both increment.

### 3.9. Compliance, Drug Testing and Welfare Enforcement

A `Steward` opens a case against an entry, naming the `opened_by_official_id` of the steward opening it and a `case_type` of `DRUG_TEST` or `WELFARE_CITATION`. A drug test carries the laboratory barcode in `sample_code` and must not carry a `welfare_rule_code`; a welfare citation carries the federation rule cited in `welfare_rule_code` and must not carry a `sample_code`. Supplying the wrong one, or omitting the required one, is `ERR_INVALID_REQUEST`. Both fields default to null. A new case has `status` of `OPEN` and `finding` of null. The show, the horse and the rider under investigation are all reached through the named entry.

Adjudication belongs to the `FederationOfficer`, who supplies a `finding` of `NEGATIVE`, `WARNING` or `POSITIVE`. Only a case in `OPEN` may be adjudicated; otherwise `ERR_CASE_ALREADY_ADJUDICATED`. `SUBSTANTIATED` and `DISMISSED` are terminal case states.

A `NEGATIVE` finding moves the case `OPEN → DISMISSED`, records `finding` as `NEGATIVE`, and does nothing else beyond incrementing the case's `version`.

A `WARNING` finding moves the case `OPEN → SUBSTANTIATED`, records `finding` as `WARNING`, and is only permitted when the case's `case_type` is `WELFARE_CITATION`; a warning on a drug test is refused with `ERR_FINDING_NOT_APPLICABLE`. Its consequence is a strike, not a suspension: the show's `welfare_strike_count` is recomputed as the number of that show's substantiated welfare citations — counted over cases whose `case_type` is `WELFARE_CITATION` and whose `status` is `SUBSTANTIATED`, reached through each case's entry — and no horse is suspended. Both the case's and the show's `version` increment. Two such strikes stop competition on the show, as §3.7 describes.

A `POSITIVE` finding moves the case `OPEN → SUBSTANTIATED`, records `finding` as `POSITIVE`, and fires the second deep cascade in the system. It is permitted for either `case_type`. In order: the entry's horse has its `eligibility_status` set to `SUSPENDED`; then every class entry anywhere in the system whose parent entry names that same horse, whose own `status` is `ENTERED`, `CONFIRMED` or `COMPLETED`, and whose class is not `VOIDED`, moves to `DISQUALIFIED` with its `prize_cents` reset to 0 and its `placing` set back to null; then every class touched by those disqualifications whose `status` was `RESULTS_POSTED` reverts `RESULTS_POSTED → JUDGED` with its `awarded_prize_cents` reset to 0 and its `placed_count`, `entry_count`, `confirmed_entry_count` and `point_eligible` recomputed; and then the show's `allocated_prize_cents` and `unallocated_prize_cents` are recomputed per the prize ledger, so the money released by the reverted classes returns to the unallocated side. The `prize_cents` reset in this cascade reaches only the rows that move to `DISQUALIFIED`: any other class entry on a reverted class keeps the `prize_cents` figure posting wrote to it, even though its class's `awarded_prize_cents` has returned to 0.

The cascade reaches standings as well. Every standings submission belonging to a class touched by the disqualifications whose `status` is `PREPARED`, `NATIONAL_ACCEPTED`, `REGIONAL_ACCEPTED` or `RECORDED` moves to `RETRACTED`, and retraction compensates: each rider's `national_points_total` and `regional_points_total` are decremented by exactly the amounts that submission credited, and the affected class entries' `points_national` and `points_regional` are reset to 0. Each retracted submission's `version` increments. When the adjudicated case's `case_type` is `WELFARE_CITATION`, a positive finding also recomputes the show's `welfare_strike_count`. The case's and the show's `version` both increment, along with those of every horse, class entry, class and submission the cascade touched.

---

## 4. Endpoint Definitions

All endpoints are mounted at the service root. Operations that bring a new resource into existence answer with HTTP 201 and the created resource in `data`; operations that modify an existing resource, including every state transition, answer with HTTP 200 and the updated resource in `data`; reads answer with HTTP 200. Error statuses are as catalogued in §5. Every request must carry the `X-User-ID` and `X-User-Role` headers described in §2.1, and every list endpoint accepts the `limit` and `offset` parameters of §2.3 alongside the filters of §2.4.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| GET | `/shows/{id}` | Fetch one show with its licensing state, stall ledger and prize ledger. | ShowSecretary, FederationOfficer, RingMaster, Judge, Steward, Exhibitor, GroundsManager |
| GET | `/shows/{id}/rings` | List the rings on this show's grounds. | ShowSecretary, FederationOfficer, RingMaster, Judge, Steward, Exhibitor, GroundsManager |
| GET | `/shows/{id}/divisions` | List this show's competition divisions. | ShowSecretary, FederationOfficer, RingMaster, Judge, Steward, Exhibitor, GroundsManager |
| GET | `/shows/{id}/coverage-shifts` | List veterinary and farrier coverage windows for this show. | ShowSecretary, FederationOfficer, RingMaster, Judge, Steward, Exhibitor, GroundsManager |
| GET | `/shows/{id}/schedule-projection` | Computed read: both duration-estimate variants for every currently scheduled or running class of the show, plus their aggregate drift. | ShowSecretary, FederationOfficer, RingMaster, Judge, Steward, Exhibitor, GroundsManager |
| GET | `/rings/{id}` | Fetch one ring with footing condition, status and schedule totals. | ShowSecretary, FederationOfficer, RingMaster, Judge, Steward, Exhibitor, GroundsManager |
| GET | `/classes/{id}` | Fetch one class with its counts, purse, estimate and point eligibility. | ShowSecretary, FederationOfficer, RingMaster, Judge, Steward, Exhibitor, GroundsManager |
| GET | `/classes` | Filtered class list, including discovery of a championship class's qualifiers. | ShowSecretary, FederationOfficer, RingMaster, Judge, Steward, Exhibitor, GroundsManager |
| GET | `/classes/{id}/point-submissions` | List standings submissions raised for this class; the only discovery channel for a submission id. | ShowSecretary, FederationOfficer, RingMaster, Judge, Steward, Exhibitor, GroundsManager |
| GET | `/ring-slots/{id}` | Fetch one ring slot with its computed window, warm-up lead and running-order index. | ShowSecretary, FederationOfficer, RingMaster, Judge, Steward, Exhibitor, GroundsManager |
| GET | `/ring-slots` | Filtered ring-slot list; the only discovery channel for maintenance slots. | ShowSecretary, FederationOfficer, RingMaster, Judge, Steward, Exhibitor, GroundsManager |
| GET | `/officials/{id}` | Fetch one official with licence facts and current assigned-minute load. | ShowSecretary, FederationOfficer, RingMaster, Judge, Steward, Exhibitor, GroundsManager |
| GET | `/official-assignments/{id}` | Fetch one official assignment. | ShowSecretary, FederationOfficer, RingMaster, Judge, Steward, Exhibitor, GroundsManager |
| GET | `/official-assignments` | Filtered assignment list. | ShowSecretary, FederationOfficer, RingMaster, Judge, Steward, Exhibitor, GroundsManager |
| GET | `/riders/{id}` | Fetch one rider with membership status re-derived against the logical clock. | ShowSecretary, FederationOfficer, RingMaster, Judge, Steward, Exhibitor, GroundsManager |
| GET | `/riders/{id}/standings` | Computed read: the rider's national and regional standings totals, scoring class count, and whether the regional per-show cap bound. | ShowSecretary, FederationOfficer, RingMaster, Judge, Steward, Exhibitor, GroundsManager |
| GET | `/horses/{id}` | Fetch one horse with computed Coggins expiry and eligibility status. | ShowSecretary, FederationOfficer, RingMaster, Judge, Steward, Exhibitor, GroundsManager |
| GET | `/entries/{id}` | Fetch one entry with both parallel status dimensions and the full settlement breakdown. | ShowSecretary, FederationOfficer, RingMaster, Judge, Steward, Exhibitor, GroundsManager |
| GET | `/entries` | Filtered entry list. | ShowSecretary, FederationOfficer, RingMaster, Judge, Steward, Exhibitor, GroundsManager |
| GET | `/class-entries/{id}` | Fetch one class entry with placing, prize and standings points. | ShowSecretary, FederationOfficer, RingMaster, Judge, Steward, Exhibitor, GroundsManager |
| GET | `/class-entries` | Filtered class-entry list. | ShowSecretary, FederationOfficer, RingMaster, Judge, Steward, Exhibitor, GroundsManager |
| GET | `/compliance-cases/{id}` | Fetch one drug-test or welfare-citation case. | ShowSecretary, FederationOfficer, RingMaster, Judge, Steward, Exhibitor, GroundsManager |
| GET | `/compliance-cases` | Filtered compliance-case list. | ShowSecretary, FederationOfficer, RingMaster, Judge, Steward, Exhibitor, GroundsManager |
| POST | `/shows` | Create a show in DRAFT licensing state. | ShowSecretary |
| POST | `/shows/{id}/license-submission` | Submit or resubmit the show's prize list to the national federation for licensing. | ShowSecretary |
| POST | `/shows/{id}/license-decision` | Federation decision on a submitted show licence. | FederationOfficer |
| POST | `/shows/{id}/rings` | Add a competition ring to the show's grounds. | ShowSecretary |
| POST | `/rings/{id}/footing-maintenance` | Record a footing pass; an unsafe resulting score holds the ring and unwinds its schedule. | GroundsManager |
| POST | `/shows/{id}/divisions` | Add a competition division to a show whose licence is still editable. | ShowSecretary |
| POST | `/divisions/{id}/classes` | Add a class to a division, optionally naming the championship class it qualifies riders for. | ShowSecretary |
| POST | `/classes/{id}/open` | Open a class for entries once the show licence is approved. | ShowSecretary |
| POST | `/officials` | Register a licensed judge, steward or technical delegate in the federation roster. | FederationOfficer |
| POST | `/official-assignments` | Assign an official to a ring slot in a specific chair. | ShowSecretary |
| POST | `/riders` | Register a federation member as a competing rider. | FederationOfficer |
| POST | `/horses` | Register a horse with its Coggins draw date. | FederationOfficer |
| POST | `/shows/{id}/entries` | Submit a horse/rider entry to a licensed show while the entry window is open. | Exhibitor |
| POST | `/entries/{id}/verify` | Verify rider membership, horse Coggins validity and horse eligibility. | ShowSecretary |
| POST | `/entries/{id}/accept` | Accept a verified entry and reserve its requested stalls against show capacity. | ShowSecretary |
| POST | `/entries/{id}/invoice` | Freeze the entry invoice: class fees, stall fees, office fee tier and total due. | ShowSecretary |
| POST | `/entries/{id}/payment` | Pay an invoiced entry in full. | Exhibitor |
| POST | `/entries/{id}/withdrawal` | Withdraw an entry, releasing stalls and refunding a paid invoice. | Exhibitor |
| POST | `/class-entries` | Enter a show entry in a specific open class. | Exhibitor |
| POST | `/ring-slots` | Book a class into a ring, computing its duration estimate, warm-up lead and running-order index. | RingMaster |
| POST | `/ring-slots/{id}/start` | Call a class into the ring. | RingMaster |
| POST | `/classes/{id}/results` | Record the judge's card: placings, round times and the class's actual ring time. | Judge |
| POST | `/classes/{id}/post-results` | Post official results and pay out the class purse across the filled ribbons. | ShowSecretary |
| POST | `/classes/{id}/void-results` | Void posted results, releasing the awarded purse back to the show's unallocated pool. | ShowSecretary |
| POST | `/classes/{id}/point-submissions` | Raise a standings submission for a posted, point-eligible class. | ShowSecretary |
| POST | `/point-submissions/{id}/acknowledgement` | Record one standings body's acknowledgement of a submission. | FederationOfficer |
| POST | `/entries/{id}/compliance-cases` | Open a drug-test or welfare-citation case against an entry. | Steward |
| POST | `/compliance-cases/{id}/finding` | Adjudicate a compliance case. | FederationOfficer |
| POST | `/shows/{id}/coverage-shifts` | Schedule an on-call veterinary or farrier coverage window for the showgrounds. | GroundsManager |
| POST | `/coverage-shifts/{id}/activate` | Provider check-in for a coverage window. | GroundsManager |
| POST | `/_clock/set_current_utc` | Test-driving capability: set the server's logical current UTC instant. | FederationOfficer |

---

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_ROLE_NOT_PERMITTED` | 403 |
| `ERR_ACTOR_NOT_RECOGNIZED` | 403 |
| `ERR_ENTRY_NOT_OWNED` | 403 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_SHOW_NOT_FOUND` | 404 |
| `ERR_RING_NOT_FOUND` | 404 |
| `ERR_DIVISION_NOT_FOUND` | 404 |
| `ERR_CLASS_NOT_FOUND` | 404 |
| `ERR_SLOT_NOT_FOUND` | 404 |
| `ERR_OFFICIAL_NOT_FOUND` | 404 |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_RIDER_NOT_FOUND` | 404 |
| `ERR_HORSE_NOT_FOUND` | 404 |
| `ERR_ENTRY_NOT_FOUND` | 404 |
| `ERR_CLASS_ENTRY_NOT_FOUND` | 404 |
| `ERR_POINT_SUBMISSION_NOT_FOUND` | 404 |
| `ERR_COMPLIANCE_CASE_NOT_FOUND` | 404 |
| `ERR_COVERAGE_SHIFT_NOT_FOUND` | 404 |
| `ERR_SHOW_LICENSE_NOT_DRAFT` | 409 |
| `ERR_SHOW_LICENSE_NOT_SUBMITTED` | 409 |
| `ERR_SHOW_LICENSE_NOT_APPROVED` | 409 |
| `ERR_SHOW_LICENSE_LOCKED` | 409 |
| `ERR_CLASS_NOT_PLANNED` | 409 |
| `ERR_CLASS_NOT_OPEN` | 409 |
| `ERR_CLASS_ALREADY_SCHEDULED` | 409 |
| `ERR_CLASS_NOT_IN_PROGRESS` | 409 |
| `ERR_CLASS_NOT_JUDGED` | 409 |
| `ERR_CLASS_RESULTS_NOT_POSTED` | 409 |
| `ERR_SLOT_NOT_SCHEDULED` | 409 |
| `ERR_RING_NOT_AVAILABLE` | 409 |
| `ERR_ENTRY_NOT_RECEIVED` | 409 |
| `ERR_ENTRY_NOT_VERIFIED` | 409 |
| `ERR_ENTRY_ALREADY_INVOICED` | 409 |
| `ERR_ENTRY_NOT_INVOICED` | 409 |
| `ERR_ENTRY_ALREADY_TERMINAL` | 409 |
| `ERR_SUBMISSION_ALREADY_FINALIZED` | 409 |
| `ERR_CASE_ALREADY_ADJUDICATED` | 409 |
| `ERR_COVERAGE_SHIFT_NOT_SCHEDULED` | 409 |
| `ERR_RIDER_MEMBERSHIP_LAPSED` | 422 |
| `ERR_COGGINS_EXPIRED` | 422 |
| `ERR_HORSE_SUSPENDED` | 422 |
| `ERR_OFFICIAL_LICENSE_INSUFFICIENT` | 422 |
| `ERR_FOOTING_UNSAFE` | 422 |
| `ERR_VET_COVERAGE_MISSING` | 422 |
| `ERR_OFFICIALS_REQUIREMENT_UNMET` | 422 |
| `ERR_WELFARE_STRIKE_LIMIT` | 409 |
| `ERR_OFFICIAL_CONFLICT_OF_INTEREST` | 409 |
| `ERR_JUDGE_NOT_ASSIGNED` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_QUALIFIER_CYCLE` | 409 |
| `ERR_ENTRY_WINDOW_CLOSED` | 409 |
| `ERR_SLOT_OUTSIDE_SHOW_WINDOW` | 409 |
| `ERR_RING_SLOT_OVERLAP` | 409 |
| `ERR_OFFICIAL_TIME_CONFLICT` | 409 |
| `ERR_JUMP_HEIGHT_OUT_OF_RANGE` | 422 |
| `ERR_CLASS_NUMBER_DUPLICATE` | 409 |
| `ERR_DIVISION_SHARE_OVERSUBSCRIBED` | 422 |
| `ERR_CLASS_FULL` | 409 |
| `ERR_DUPLICATE_CLASS_ENTRY` | 409 |
| `ERR_OFFICIAL_LOAD_EXCEEDED` | 409 |
| `ERR_NO_ENTRIES_TO_JUDGE` | 409 |
| `ERR_INVALID_PLACINGS` | 422 |
| `ERR_CLASS_NOT_POINT_ELIGIBLE` | 409 |
| `ERR_CLASS_LIST_INCOMPLETE` | 422 |
| `ERR_FINDING_NOT_APPLICABLE` | 422 |
| `ERR_COVERAGE_CHECKIN_TOO_EARLY` | 409 |
| `ERR_STALL_CAPACITY_EXCEEDED` | 409 |
| `ERR_PRIZE_POOL_EXCEEDED` | 409 |
| `ERR_UNPAID_PLACED_ENTRY` | 402 |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 |

