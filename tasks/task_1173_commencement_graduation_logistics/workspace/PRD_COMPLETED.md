# Commencement Graduation Logistics API — Product Requirements Document

## 1. Introduction

Every spring the graduation committee runs the same high-stakes gauntlet: decide who is actually eligible to walk, apportion a fixed seat inventory into guest tickets without exceeding venue capacity, get the right regalia into the right hands, print diplomas whose Latin honors exactly match the registrar's final audit, keep name-pronunciation cards collected and locked before the reader rehearsed, and hold a rain plan in reserve that — if invoked — shrinks the venue and forces painful, deterministic choices about who keeps a seat. Today this work lives in spreadsheets and email threads, and every hand-off between the registrar's office, the committee chair, and the venue coordinator is an opportunity for a stale number to become a wrong diploma or an overbooked arena.

This document specifies a single API through which the committee, the registrar's office, venue staff, graduates, and external livestream and photography vendors coordinate the entire commencement lifecycle. The design is built around one governing idea: the ceremony's **readiness posture** is the master gate. Eligibility audits run only while the audit window is open; honor designations exist in a provisional form during the audit and a final form after the audit locks; ticket grants, seating charts, diploma print batches, vendor contracts, and rehearsal conduct enforcement each attach to specific postures; and the rain plan may only be invoked once the audit has locked. Two independent state dimensions — readiness and weather — therefore shape every operation a client can perform.

Because so much of the workflow allocates scarce, contested resources (graduate seats, guest tickets, accessible inventory, print batches), the specification leans on deterministic selection orders, exact monetary arithmetic in integer cents, version-pinned snapshots of honor designations, optimistic concurrency on contested records, and segregation-of-duties rules that prevent any single operator from both creating and releasing a print batch, both recording and waiving a conduct strike, or both approving and fulfilling an accessibility accommodation.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every API call must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the caller's role. The declared role must be one of five exact values: `CommitteeChair`, `RegistrarOfficer`, `VenueCoordinator`, `Graduate`, or `Vendor`. A request whose headers are missing, or whose `X-User-Role` value is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but not listed among the roles authorized for the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The five roles partition the work. A `CommitteeChair` owns the ceremony lifecycle (creation, configuration, audit open/lock/reopen, readiness, commencement, completion), runs the ticket waterfall, decides appeals, approves reader cards, fulfills regalia, issues diplomas, and manages vendor contracts. A `RegistrarOfficer` imports graduate records, runs eligibility audits, posts grade revisions, and manages print batches and diploma-correction decisions. A `VenueCoordinator` manages venues, toggles the rain plan, builds the seating chart, runs rehearsal sessions (check-in, completion, strike waivers), and processes accommodation requests. A `Graduate` acts only on their own records — ticket requests and releases, regalia orders, reader cards, accommodation requests, diploma corrections, appeals, confirmation, withdrawal, and rehearsal registration. A `Vendor` is an external livestream or photography operator whose only write is submitting the deliverable on their own contracts.

Identity is anchored differently per role. When `X-User-Role` is `Graduate`, `X-User-ID` is the `id` of the acting Graduate; ownership checks on any resource that references a Graduate compare the resource's graduate foreign-key field to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403). When `X-User-Role` is `CommitteeChair`, `RegistrarOfficer`, `VenueCoordinator`, or `Vendor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `audited_by_user_id` on an eligibility audit, `created_by_user_id` or `released_by_user_id` on a print batch, `approved_by_user_id` on a reader card or accommodation request, `recorded_by_user_id` or `waived_by_user_id` on a rehearsal attendance) but does not compare it to any entity's `id`. One comparison point exists despite this opacity: when a `Vendor` submits a deliverable, the target contract's `vendor_user_id` must equal the caller's `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN_OWNERSHIP`.

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

All list endpoints accept the query parameters `limit` and `offset`. The `limit` parameter defaults to 10, with a minimum of 1 and a maximum of 100; the `offset` parameter defaults to 0, with a minimum of 0; out-of-range or non-integer values are rejected with `ERR_INVALID_REQUEST`. List responses order their items by `created_at` ascending, and the `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset` plus the number of items in the returned page is still less than `total_count`.

Beyond paging, list endpoints accept resource-appropriate optional filters: `status` is accepted on the graduate, ticket-allocation, seat-assignment, regalia-order, accommodation-request, vendor-contract, print-batch, and rehearsal-attendance lists; `honor_tier` narrows the graduate list; `request_type` narrows the accommodation-request list; and `vendor_type` narrows the vendor-contract list.

### 2.4. Resource Identity, Timestamps, and Versions

All fourteen resource types in this system — Ceremony, Venue, Graduate, EligibilityAudit, TicketAllocation, RegaliaOrder, SeatAssignment, ReaderCard, PrintBatch, Diploma, RehearsalSession, RehearsalAttendance, AccommodationRequest, and VendorContract — share the same four system-managed properties. The `id` is a server-minted UUID with no type prefix. The `created_at` timestamp records the creation instant as an ISO 8601 UTC value; like every entity timestamp (including `checked_in_at`), it is stamped from the logical clock of §2.10 and rendered exactly as the clock's current string. The `updated_at` timestamp follows the same rule and is refreshed on every mutation. The `version` is an integer that starts at 1 when the resource is created and increments by exactly one on every mutation of the resource; clients read it and present it back under the optimistic-concurrency protocol described in §2.6.

### 2.5. Ceremony Posture and Weather Mode

A ceremony carries two independent state dimensions. The `readiness_posture` dimension walks a single lifecycle: `PLANNING`, then `AUDIT_OPEN`, then `AUDIT_LOCKED` (from which it may either revert to `AUDIT_OPEN` or advance to `READY`), then `COMMENCED`, and finally the terminal `COMPLETED`. The `weather_mode` dimension toggles between `FAIR` and `RAIN_PLAN_ACTIVE` and is entirely parallel: it may be flipped only while the posture is `AUDIT_LOCKED` or `READY`, and it never changes the posture itself. Every posture transition and every weather toggle increments the ceremony's `version` by one.

The posture gates nearly every operation in the system, and a violation is always rejected with `ERR_CEREMONY_POSTURE_FORBIDS` (HTTP 409). The gate table is:

- Eligibility audits and guest-ticket requests run only while the posture is `AUDIT_OPEN`.
- Queuing a diploma into a print batch requires `AUDIT_LOCKED` or `READY`; activating a vendor contract requires `AUDIT_LOCKED`, `READY`, or `COMMENCED`.
- Releasing a print batch requires `AUDIT_LOCKED`, `READY`, `COMMENCED`, or `COMPLETED`, so that post-ceremony correction reprints remain releasable.
- Issuing a printed diploma requires `COMMENCED`.
- Vendor deliverable submission requires `COMMENCED` or `COMPLETED`.
- Rain-plan activation and deactivation require `AUDIT_LOCKED` or `READY`.
- Posting a grade revision requires `AUDIT_LOCKED`.

Operations not listed above are not posture-gated unless their own narrative in §3 says otherwise; confirmation and withdrawal, for example, are blocked only once the ceremony is `COMPLETED`, and the block is rejected with `ERR_CEREMONY_POSTURE_FORBIDS`.

### 2.6. Optimistic Concurrency Control

Two write endpoints are guarded by optimistic concurrency control, and both use the same protocol: the request must carry a non-optional field naming the version the client last observed, and if that value does not equal the target entity's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

- Updating a ceremony's configuration requires `expected_ceremony_version`, matched against the ceremony's current `version`. If any intervening write — a configuration update or any lifecycle action — has advanced the ceremony's version since the client last read it, the update is rejected, so the client never overwrites a configuration it has not observed.
- Posting a guest-ticket request requires `expected_ticket_allocation_version`, matched against the allocation's current `version`. Because a new request supersedes the allocation's prior request terms, a mismatch means the client is about to silently overwrite request terms it never saw, and the request is rejected.

Endpoints not listed in this section take no version field at all.

### 2.7. Segregation of Duties

Three workflows split a sensitive pair of steps across two different operators. In each pair, the second step is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) when the same `X-User-ID` performs both:

- A print batch may be released only by a `RegistrarOfficer` whose identifier differs from the batch's `created_by_user_id`.
- A rehearsal absence may be waived only by a `VenueCoordinator` whose identifier differs from the attendance's `recorded_by_user_id`.
- An accommodation request may be fulfilled only by a `VenueCoordinator` whose identifier differs from the request's `approved_by_user_id`.

### 2.8. Numeric Precision, Rounding, and Money

Grade-point averages are carried to exactly 3 decimal places, rounded half up, and the rounding is applied **before** any threshold comparison; all threshold comparisons are inclusive of the boundary. All monetary values are integer cents, and every monetary rounding is half up to a whole cent; regalia discounts in particular are rounded per line item and then summed — never summed first and rounded once. Ticket pool sizes are integers, with pool totals rounded down to a whole number when a fractional ratio is applied to a capacity. All counts (strikes, seats, tickets, diplomas) are integers; the conduct revocation boundary is "at least 2", meaning exactly 2 strikes already revokes.

### 2.9. Capacity Pools and Inventory Accounting

Four computed quantities on the ceremony keep every allocation honest, and they are recomputed on ceremony creation, on rain-plan toggles, on seat assignment and eviction, on ceremony completion, and on every ticket waterfall, grant, or release. Pool recomputation by itself never increments the ceremony's `version` nor refreshes its `updated_at`. The **effective venue** is the ceremony's primary venue while `weather_mode` is `FAIR`, and the rain venue while `weather_mode` is `RAIN_PLAN_ACTIVE`. The `effective_capacity` is the effective venue's `total_capacity`. The `open_seat_count` is the `effective_capacity` minus the number of seat assignments in `ASSIGNED` status for the ceremony. The `ticket_pool_total` is the `effective_capacity` multiplied by the ceremony's `ticket_ratio`, rounded down to a whole number. The `ticket_pool_remaining` is the `ticket_pool_total` minus the sum of `granted_count` over all of the ceremony's ticket allocations whose status is `PENDING`, `ALLOCATED`, `PARTIAL`, or `WAITLISTED` — allocations in `RELEASED` or `EXPIRED` contribute nothing.

Alongside the general seat inventory, each venue declares an `accessible_capacity` describing the size of its wheelchair-accessible seat pool; this pool is consumed by approved wheelchair accommodations and by seat assignments flagged `accessible`, and it is measured against the *effective* venue whenever the rain plan changes which venue is effective.

### 2.10. Deadlines, Windows, and the Logical Clock

All temporal rules in the system read a single logical clock, not wall-clock time. Before any client call sets it, the logical clock reads the fixed default `2026-05-01T00:00:00Z`, and the server must never fall back to wall-clock time. A test-driving capability, restricted to `CommitteeChair`, `RegistrarOfficer`, and `VenueCoordinator`, advances the clock to a supplied `to_iso8601` instant and reports the resulting `current_utc`; any parseable ISO 8601 instant is accepted and stored verbatim, so the clock need not move forward.

Three per-ceremony deadlines and two day-counted windows share one boundary convention: the deadline instant itself is still on time, and only a submission strictly after the instant is rejected. A ticket request posted strictly after the ceremony's `ticket_request_deadline` is rejected with `ERR_REQUEST_WINDOW_CLOSED`; a reader card submitted strictly after the `pronunciation_deadline` is rejected with `ERR_PRONUNCIATION_DEADLINE_PASSED`; a regalia order created strictly after the `regalia_order_deadline` is not rejected but incurs the late fee described in §3.4. An appeal filed strictly after fourteen days from the audit's `created_at` is rejected with `ERR_APPEAL_WINDOW_CLOSED`, and a diploma correction requested strictly after thirty days from the ceremony's `ceremony_date` is rejected with `ERR_CORRECTION_WINDOW_CLOSED`.

### 2.11. Validation Evaluation Order

When several checks could reject the same call, the server evaluates them in one fixed global order and surfaces only the first failure. The order is:

1. Authentication — headers present and role declared, else `ERR_UNAUTHENTICATED`.
2. Endpoint role membership — the caller's role appears in the endpoint's authorized list, else `ERR_UNAUTHORIZED_ROLE`.
3. Path existence — path-templated resources are resolved left to right along the URL, and the first missing resource yields `ERR_NOT_FOUND`.
4. Ownership — a `Graduate` may touch only their own resources (the caller's `X-User-ID` must equal the `graduate_id` of the target chain), and a `Vendor` may submit deliverables only on contracts whose `vendor_user_id` equals the caller's `X-User-ID`, else `ERR_FORBIDDEN_OWNERSHIP`.
5. Body schema — required fields present, types valid, enum values inside their declared domains, and ranges valid (a requested ticket count of at least one, an `end_utc` strictly after its `start_utc`, capacities of at least one, amounts of at least zero), else `ERR_INVALID_REQUEST`.
6. Segregation of duties — the three split-duty pairs of §2.7, else `ERR_SEGREGATION_OF_DUTIES`.
7. Optimistic concurrency — `expected_ceremony_version` or `expected_ticket_allocation_version` equals the entity's current `version`, else `ERR_STALE_VERSION`.
8. The target entity's own state machine permits the transition from its current state, else `ERR_INVALID_STATE`.
9. The ceremony posture gate of §2.5, else `ERR_CEREMONY_POSTURE_FORBIDS`.
10. The graduate eligibility gate — the graduate's `status` is `ELIGIBLE`, `ELIGIBLE_ON_APPEAL`, or `CONFIRMED` for ticket requests, reader-card creation, rehearsal registration, diploma queueing, and seat assignment, else `ERR_GRADUATE_NOT_ELIGIBLE`.
11. The conduct gate — the graduate's `walk_privilege_revoked` is false for regalia fulfillment, else `ERR_WALK_PRIVILEGE_REVOKED`.
12. Temporal windows, evaluated in this relative order: the ticket request window (`ERR_REQUEST_WINDOW_CLOSED`), then the pronunciation deadline (`ERR_PRONUNCIATION_DEADLINE_PASSED`), then the appeal window (`ERR_APPEAL_WINDOW_CLOSED`), then the correction window (`ERR_CORRECTION_WINDOW_CLOSED`).
13. The ticket entitlement cap, else `ERR_TICKET_CAP_EXCEEDED`.
14. Seat-position uniqueness, else `ERR_SEAT_CONFLICT`.
15. General seat capacity, else `ERR_SEAT_CAPACITY_EXCEEDED`.
16. The accessible-seat pool, else `ERR_ACCESSIBLE_CAPACITY_EXCEEDED`.
17. Rehearsal venue time overlap, else `ERR_VENUE_TIME_OVERLAP`.
18. Vendor coverage overlap, else `ERR_VENDOR_COVERAGE_OVERLAP`.
19. Reader-card uniqueness, else `ERR_READER_CARD_EXISTS`.
20. Duplicate rehearsal registration, else `ERR_DUPLICATE_REGISTRATION`.
21. Rehearsal session capacity, else `ERR_REHEARSAL_FULL`.
22. Rain venue configured, else `ERR_RAIN_VENUE_MISSING`.
23. Honor snapshot freshness, else `ERR_HONOR_SNAPSHOT_STALE`.
24. An open reprint batch exists, else `ERR_NO_OPEN_REPRINT_BATCH`.
25. Batch non-emptiness, else `ERR_BATCH_NOT_RELEASABLE`.
26. Vendor deliverable presence, else `ERR_VENDOR_DELIVERABLE_MISSING`.
27. Payment exactness, else `ERR_PAYMENT_AMOUNT_MISMATCH`.

A consequence worth internalizing: on a ticket request, the request-window rejection (`ERR_REQUEST_WINDOW_CLOSED`) always surfaces before the entitlement-cap rejection (`ERR_TICKET_CAP_EXCEEDED`), and both are masked by a stale allocation version (`ERR_STALE_VERSION`), a closed audit window (`ERR_CEREMONY_POSTURE_FORBIDS`), or an ineligible graduate (`ERR_GRADUATE_NOT_ELIGIBLE`).

## 3. Business Logic & Workflows

### 3.1. Venues, Ceremony Setup, and the Readiness Lifecycle

Before anything else exists, a `VenueCoordinator` registers the physical spaces. Each venue record carries a `name`, a street `address`, a `total_capacity` of at least one graduate seat, an `accessible_capacity` of at least zero and no greater than the `total_capacity`, and an `indoor` flag. Venues are referenced twice over by ceremonies — once as the primary site and optionally again as the rain site — and venue read endpoints expose the reverse lookups, listing the ceremonies that use a venue in either role and the rehearsal sessions booked at it.

With a venue on file, a `CommitteeChair` creates the ceremony. Creation takes the display `name`, the scheduled `ceremony_date` in UTC (the instant from which the post-ceremony correction window is measured), the `venue_id` of the primary fair-weather site, and an optional `rain_venue_id` that stays null until a rain site is designated. The ticketing policy arrives as three numbers: a `ticket_ratio` greater than zero expressing how many guest tickets are issued per venue seat, a `guest_ticket_base_cap` of at least zero giving each graduate's base guest-ticket entitlement, and an `honor_bonus_tickets` of at least zero added for graduates with honors. Three deadlines — `pronunciation_deadline`, `ticket_request_deadline`, and `regalia_order_deadline` — bound the workflows of §3.6, §3.3, and §3.4 respectively, and an optional `rehearsal_required` flag, defaulting to true, declares whether the rehearsal conduct policy of §3.6 is enforced for this ceremony. A new ceremony starts in `PLANNING` posture with `FAIR` weather, and its pools are initialized immediately from the primary venue: `effective_capacity` and `open_seat_count` both start at the venue's `total_capacity`, `ticket_pool_total` is the capacity multiplied by the `ticket_ratio` rounded down, and `ticket_pool_remaining` starts equal to the pool total.

The chair may reshape its configuration in any posture — the configuration update is itself not posture-gated — covering `name`, `ticket_ratio`, `guest_ticket_base_cap`, `honor_bonus_tickets`, the three deadlines, or the `rain_venue_id` (which may also be cleared back to null), through a configuration update that is guarded by optimistic concurrency as described in §2.6: the request must carry `expected_ceremony_version`, and a stale value is rejected with `ERR_STALE_VERSION`. A successful update increments the ceremony's `version`, and when the `ticket_ratio` changes, the pool fields are recomputed.

The readiness lifecycle then proceeds under the chair's hand. Opening the audit moves `PLANNING` to `AUDIT_OPEN`. Locking the audit moves `AUDIT_OPEN` to `AUDIT_LOCKED` and finalizes honor designations as detailed in §3.2. Reopening the audit returns `AUDIT_LOCKED` to `AUDIT_OPEN`, but only while no print batch for the ceremony stands in `RELEASED` or `PRINTED` status — if one does, the revert is rejected with `ERR_INVALID_STATE`, because finalized honor text has already left the building. Marking the ceremony ready moves `AUDIT_LOCKED` to `READY` and is permitted only when no non-`WITHDRAWN` graduate remains in `PENDING_AUDIT` or `APPEALING` status and every graduate in `ELIGIBLE`, `ELIGIBLE_ON_APPEAL`, or `CONFIRMED` has a reader card in `SUBMITTED` or `APPROVED` status; either failure is rejected with `ERR_CEREMONY_POSTURE_FORBIDS`. Marking ready also cascades through the reader-card population, moving every `SUBMITTED` or `APPROVED` card for the ceremony's graduates to `LOCKED`. Commencing moves `READY` to `COMMENCED`, and completing moves `COMMENCED` to the terminal `COMPLETED`. Completion sweeps the ticket book: every allocation still `PENDING` or `WAITLISTED` for the ceremony moves to `EXPIRED`, its `granted_count` zeroed and its `waitlist_position` cleared. Each of these lifecycle actions increments the ceremony's `version` by one.

### 3.2. Graduate Import, Eligibility Audit, Appeals, and Honor Designation

A `RegistrarOfficer` populates the graduating class by importing records one at a time. Each import names the `ceremony_id`, the student's `full_name` (the legal name that becomes the default printed name on the diploma) and `email`, the academic ledger — `institutional_gpa_credits` and `institutional_quality_points`, each at least zero; optional `transfer_gpa_credits` and `transfer_quality_points`, defaulting to zero; `credits_completed` at least zero and `credits_required` at least one — and an optional `outstanding_hold_count` defaulting to zero. The new graduate starts in `PENDING_AUDIT` status with `honor_tier` `NONE`, `honor_basis` `NONE`, a `conduct_strike_count` of zero, and `walk_privilege_revoked` false. Import also auto-creates the graduate's ticket allocation in `PENDING` status with a `requested_count` of zero (`granted_count`, `provisional_granted_count`, and `entitlement_count` likewise zero, `waitlist_position` null) — the allocation exists from birth so that the ticket workflow of §3.3 always has a record to mutate.

Audits run only while the ceremony's posture is `AUDIT_OPEN`; an attempt in any other posture is rejected with `ERR_CEREMONY_POSTURE_FORBIDS`. A `RegistrarOfficer` audits a graduate who is still `PENDING_AUDIT` (any other status is rejected with `ERR_INVALID_STATE`), optionally attaching free-text `notes` (stored as an empty string when omitted). The audit computes eligibility deterministically from the imported ledger: the graduate **passes** when `credits_completed` is at least `credits_required` — meeting the requirement exactly passes — **and** `outstanding_hold_count` is exactly zero **and** `institutional_gpa_credits` is strictly greater than zero. On a pass, the audit's `result` is `PASS`, its `fail_reasons` array is empty, and the graduate advances to `ELIGIBLE`. On a failure, the `result` is `FAIL`, the `fail_reasons` array accumulates the applicable subset of `INSUFFICIENT_CREDITS` (credits short of the requirement), `OUTSTANDING_HOLD` (an unresolved hold), and `NO_INSTITUTIONAL_CREDITS` (no institutional GPA credits), and the graduate drops to `INELIGIBLE`. Either way the audit records the caller as `audited_by_user_id`, starts with `appeal_status` `NONE` and a null `decided_by_user_id`, and the graduate's `version` increments.

Every audit also takes the graduate's provisional honor snapshot. The honor machinery has two variants of one calculation, and the distinction matters all the way to the printed diploma. The shared core: a graduate's GPA is their quality points divided by their GPA credits, rounded half up to three decimal places **before** any comparison; when the credit denominator is zero the GPA is 0.000. The tier ladder is inclusive at every rung: a GPA of at least 3.900 earns `SUMMA_CUM_LAUDE`, at least 3.700 earns `MAGNA_CUM_LAUDE`, at least 3.500 earns `CUM_LAUDE`, and anything below earns `NONE`. The **COMBINED** variant — the provisional designation — divides the sum of `institutional_quality_points` and `transfer_quality_points` by the sum of `institutional_gpa_credits` and `transfer_gpa_credits`, so transfer work counts; it is computed at audit creation, on audit reopening, and on appeal approval. The **INSTITUTIONAL** variant — the final designation — divides `institutional_quality_points` by `institutional_gpa_credits` alone, excluding transfer work; it is computed when the audit locks and when grades are revised, and it is the variant printed on diplomas and consumed by the ticket honor bonus. The two variants can legitimately yield different tiers for identical graduate data. At audit time the provisional COMBINED tier is written to the graduate's `honor_tier` with `honor_basis` `COMBINED`, and snapshotted onto the audit as `provisional_honor_tier` — `NONE` when the audit result is `FAIL`. Honor tiers are only ever recomputed for graduates in the eligible family — `ELIGIBLE`, `ELIGIBLE_ON_APPEAL`, or `CONFIRMED`; graduates who are `INELIGIBLE`, `PENDING_AUDIT`, or `WITHDRAWN` keep `NONE`.

Two ceremony-level events re-run the honor machinery across the whole class. Locking the audit recomputes the FINAL INSTITUTIONAL variant for every graduate in `ELIGIBLE`, `ELIGIBLE_ON_APPEAL`, or `CONFIRMED`, updating each graduate's `honor_tier` and setting `honor_basis` to `INSTITUTIONAL`. Reopening the audit recomputes the PROVISIONAL COMBINED variant for every audited, non-`WITHDRAWN` graduate in the eligible family, setting `honor_basis` back to `COMBINED` — and because this can change tiers after diplomas have been queued, it may strand the version-pinned honor snapshots described in §3.7, which is exactly what the batch-release freshness check exists to catch. Within a locked audit, a `RegistrarOfficer` may also post a grade revision for a single graduate — any of `institutional_gpa_credits`, `institutional_quality_points`, `transfer_gpa_credits`, or `transfer_quality_points` — where the `AUDIT_LOCKED` posture gate fires before the posted fields are validated and the graduate's own status is not otherwise checked; the revision recomputes that graduate's FINAL INSTITUTIONAL honor, increments the graduate's `version`, and carries the same risk of staling queued diploma snapshots.

The appeal loop gives a failed graduate one structured shot at reversal. A graduate whose status is `INELIGIBLE` may appeal their latest audit — and only their latest — while its `appeal_status` is still `NONE` and no more than fourteen days have passed since the audit's `created_at`; filing strictly after the fourteen-day mark is rejected with `ERR_APPEAL_WINDOW_CLOSED` — the window check fires before the already-appealed check, so a late filing on an already-appealed audit still surfaces `ERR_APPEAL_WINDOW_CLOSED`. Filing moves the graduate to `APPEALING` and the audit's `appeal_status` to `SUBMITTED`. A `CommitteeChair` then decides with a `decision` value. Both branches require the graduate to be `APPEALING` and the audit's `appeal_status` to be `SUBMITTED`. An `APPROVED` decision moves the graduate to `ELIGIBLE_ON_APPEAL`, sets the audit's `appeal_status` to `APPROVED` and its `decided_by_user_id` to the deciding chair, and recomputes the graduate's PROVISIONAL COMBINED honor with `honor_basis` `COMBINED`. A `DENIED` decision returns the graduate to `INELIGIBLE` and sets the audit's `appeal_status` to `DENIED` and its `decided_by_user_id` to the deciding chair. Either branch increments the graduate's `version`.

Once eligible by any path, a graduate confirms their own attendance: confirmation moves `ELIGIBLE` to `CONFIRMED`, or `ELIGIBLE_ON_APPEAL` to `CONFIRMED`, and is unavailable once the ceremony has reached `COMPLETED`. Confirmation is a courtesy signal for planning; it does not unlock any capability that eligibility alone does not. The `COMPLETED` block is evaluated before the graduate's own status check, so a confirmation attempted after completion is rejected with `ERR_CEREMONY_POSTURE_FORBIDS` regardless of the graduate's status.

### 3.3. Guest Ticketing: Requests, the Waterfall, and the Waitlist

Guest ticketing is a quota system draped over the seat inventory. Every graduate owns exactly one allocation — created at import in `PENDING` status with `requested_count` zero — and the allocation's lifecycle runs `PENDING`, `ALLOCATED`, `PARTIAL`, `WAITLISTED`, with `RELEASED` and `EXPIRED` as the two terminal exits. The ceremony's pool arithmetic from §2.9 supplies the inventory: `ticket_pool_total` is the effective capacity times the `ticket_ratio` rounded down, and `ticket_pool_remaining` is what is left after subtracting grants on non-terminal allocations.

A graduate files or re-files their request while the audit window is open. The checks fire in the order of §2.11: the ceremony's posture must be `AUDIT_OPEN` (else `ERR_CEREMONY_POSTURE_FORBIDS`), the graduate's `status` must be `ELIGIBLE`, `ELIGIBLE_ON_APPEAL`, or `CONFIRMED` (else `ERR_GRADUATE_NOT_ELIGIBLE`), the request must arrive no later than the ceremony's `ticket_request_deadline` (strictly after is `ERR_REQUEST_WINDOW_CLOSED`), and the `requested_count` must be at least one (else `ERR_INVALID_REQUEST`) and no greater than the graduate's entitlement — the ceremony's `guest_ticket_base_cap` plus, for a graduate whose current `honor_tier` is anything other than `NONE`, the ceremony's `honor_bonus_tickets`; asking for exactly the entitlement is allowed, and asking for more is rejected with `ERR_TICKET_CAP_EXCEEDED`. Because a new request supersedes the prior request terms, the call is concurrency-guarded per §2.6 and must carry `expected_ticket_allocation_version`; a stale value is rejected with `ERR_STALE_VERSION`. The allocation's status at filing time must be `PENDING`, `ALLOCATED`, `PARTIAL`, or `WAITLISTED`. A successful filing updates `requested_count`, recomputes `provisional_granted_count`, and increments the allocation's `version`.

The provisional figure deserves its own paragraph because it is an estimate and nothing more. At filing time the server computes the PROVISIONAL waterfall variant: the smaller of the `requested_count`, the entitlement evaluated with the graduate's **current** `honor_tier` (which, mid-audit, may still be a COMBINED provisional tier), and the ceremony's **current** `ticket_pool_remaining` under the current weather, clamped at zero so the estimate is never negative. The result is stored on `provisional_granted_count`; it never mutates the pool, and it may diverge from the FINAL grant computed later under finalized tiers or a shrunken rain-plan capacity.

The FINAL waterfall is run by a `CommitteeChair` and is also re-run by the rain-plan and promotion machinery below. Its scope is every allocation of the ceremony in `PENDING`, `ALLOCATED`, `PARTIAL`, or `WAITLISTED` status with a `requested_count` of at least one — `RELEASED` and `EXPIRED` allocations are out, and a `PENDING` allocation that never requested simply stays `PENDING`. The run first resets every in-scope allocation's `granted_count` to zero, then walks the **waterfall order**: honor rank descending (`SUMMA_CUM_LAUDE` outranks `MAGNA_CUM_LAUDE`, which outranks `CUM_LAUDE`, which outranks `NONE`), then `requested_count` descending, then the allocation's `created_at` ascending — the allocation `id` is never a tiebreaker. Each allocation's target is the smaller of its `requested_count` and its entitlement, and its `entitlement_count` is snapshotted at each waterfall run. Walking in order, the run grants each allocation the smaller of its target and the pool remaining, debiting the pool by the grant. A grant equal to the target lands the allocation in `ALLOCATED` with its `waitlist_position` cleared to null; a grant strictly between zero and the target lands it in `PARTIAL`; a grant of exactly zero lands it in `WAITLISTED`, assigned a 1-based `waitlist_position` ranking it among the zero-grant allocations in waterfall order. The run reports `processed_count`, `granted_total`, `waitlisted_count`, and the closing `pool_remaining`. The run increments the `version` of every in-scope allocation it walks; the ceremony's own `version` is not incremented by a waterfall run.

Pool increases do not idle. Whenever inventory returns — a release, a withdrawal, or rain-plan deactivation — a **promotion scan** walks the still-unsatisfied allocations (`PARTIAL` and `WAITLISTED`) in waterfall order and tops each up by the smaller of its remaining gap to target and the pool remaining, debiting the pool as it goes. A top-up that closes the gap promotes the allocation to `ALLOCATED`, setting `granted_count` to the full target and clearing `waitlist_position`; a top-up on a `WAITLISTED` allocation that does not close the gap moves it to `PARTIAL` with `granted_count` increased and `waitlist_position` cleared; a `PARTIAL` allocation that receives less than its gap simply holds the larger `granted_count`. The scan re-snapshots each visited allocation's `entitlement_count` as it goes and, afterwards, renumbers the `waitlist_position` of the allocations still `WAITLISTED` 1-based in waterfall order; a pure renumbering refreshes `updated_at` without incrementing the allocation's `version`.

A graduate may also give tickets back. Releasing an allocation — permitted from `PENDING`, `ALLOCATED`, `PARTIAL`, or `WAITLISTED` — credits the full `granted_count` back to `ticket_pool_remaining`, zeroes `granted_count`, clears `waitlist_position`, moves the allocation to the terminal `RELEASED`, increments its `version`, and immediately fires the promotion scan over the remaining `WAITLISTED` and `PARTIAL` allocations in waterfall order. Withdrawal, covered in §3.9, releases through the same machinery. Finally, when the ceremony completes, every allocation still `PENDING` or `WAITLISTED` expires to `EXPIRED` with its grant zeroed and waitlist position cleared.

### 3.4. Regalia Ordering, Pricing, and Distribution

Regalia runs a small order-to-pickup pipeline with exact-cent arithmetic. A graduate submits an order containing an `items` array of one or more lines — an empty array is rejected with `ERR_INVALID_REQUEST` — each line carrying an `item_type`, a `size`, a `quantity` of at least one, and a `unit_price_cents` of at least zero. The order is priced once, at creation, by a pinned evaluation order. First, each line's total is its `unit_price_cents` multiplied by its `quantity`, and `subtotal_cents` is the sum of the line totals. Second, the discount percentage is keyed on the **pre-discount** subtotal: fifteen percent when `subtotal_cents` is at least 20,000 cents, otherwise ten percent when it is at least 10,000 cents, otherwise no discount. Third, `discount_cents` is the sum of the **per-line** discounts, each line's discount computed as its line total multiplied by the percentage and rounded half up to a whole cent — summing the raw discounts and rounding once produces different cents and is not acceptable. Fourth, the late fee: an order created strictly after the ceremony's `regalia_order_deadline` adds a `late_fee_cents` of ten percent of the already-discounted subtotal, rounded half up; an order created at the deadline instant itself is on time and carries a `late_fee_cents` of zero. Finally, `total_cents` is the discounted subtotal plus the late fee. Requesting an exchange later does not re-price the order. A new order stands in `SUBMITTED` status.

Payment is exact-change only. The graduate pays by presenting `amount_cents`, and the order moves `SUBMITTED` to `PAID` only when the presented amount equals the order's `total_cents` exactly; any discrepancy is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 402), and any attempt to pay an order not in `SUBMITTED` is rejected with `ERR_INVALID_STATE`. Distribution is the chair's job: fulfillment moves a `PAID` order — or an `EXCHANGE_REQUESTED` one, in the exchange loop below — to `FULFILLED`, but only while the graduate's `walk_privilege_revoked` is false; a graduate who has accumulated two or more unexcused rehearsal strikes (§3.6) is refused with `ERR_WALK_PRIVILEGE_REVOKED`.

The exchange loop handles the inevitable wrong-size gown. A graduate whose order is `FULFILLED` may request an exchange — optionally noting a `reason`, which is accepted but not stored on the order — moving the order to `EXCHANGE_REQUESTED`, from which the chair re-fulfills it under exactly the same gate as a first fulfillment (status in `PAID` or `EXCHANGE_REQUESTED`, walk privilege intact). Cancellation is a pre-payment escape hatch only: a graduate may cancel an order while it is `SUBMITTED`, moving it to the terminal `CANCELLED`; orders already `PAID` or `FULFILLED` cannot be cancelled this way, and as §3.9 notes, even a full withdrawal cancels only `SUBMITTED` orders.

### 3.5. Seating Chart, Accessibility Accommodations, and the Rain Plan

The seating chart maps eligible graduates onto the effective venue one assignment at a time, or in one deterministic sweep. A `VenueCoordinator` places a graduate manually by naming the `ceremony_id`, the `graduate_id`, a `section` label, a `row_label` within the section, a `seat_number` of at least one within the row, and an optional `accessible` flag defaulting to false. The named graduate is not checked to belong to the named ceremony. Manual placement enforces three constraints in the order of §2.11: the seat position must be unique among the ceremony's `ASSIGNED` seats and the graduate must not already hold an `ASSIGNED` seat (either violation is `ERR_SEAT_CONFLICT`); the count of `ASSIGNED` seats must be below the ceremony's `effective_capacity` before placing (else `ERR_SEAT_CAPACITY_EXCEEDED`); and an `accessible` placement requires the count of `ASSIGNED` accessible seats to be below the effective venue's `accessible_capacity` (else `ERR_ACCESSIBLE_CAPACITY_EXCEEDED`). The graduate must also pass the eligibility gate of §2.11 (else `ERR_GRADUATE_NOT_ELIGIBLE`). Each new assignment stands `ASSIGNED` with a null `evicted_reason` and decrements `open_seat_count` by one; each eviction — manual or cascading — increments it by one.

The automated sweep seats everyone at once. On the chair's signal the coordinator runs the seating pass: candidates are the ceremony's graduates in `ELIGIBLE`, `ELIGIBLE_ON_APPEAL`, or `CONFIRMED` who hold no `ASSIGNED` seat, ordered by honor rank descending and then by the graduate's `created_at` ascending. Seats are dealt from a cursor rooted at section `A` — rows numbered from 1 upward, exactly four seats per row — and each candidate receives the lowest row-and-seat combination not occupied by an `ASSIGNED` seat. A candidate holding an `APPROVED` or `FULFILLED` wheelchair accommodation can be seated only while the count of `ASSIGNED` accessible seats remains below the effective venue's `accessible_capacity`; if the accessible pool is exhausted the candidate is skipped and remains unassigned, and when seated, their assignment is flagged `accessible`. Every candidate who cannot be seated — whether because the accessible pool is exhausted or because no free seat remains under `effective_capacity` — is passed over and counted in `skipped_count` while the sweep continues with the next candidate, and the sweep reports `assigned_count`, `skipped_count`, and the resulting `open_seat_count`. A coordinator may also evict any `ASSIGNED` seat by hand, which moves it to the terminal `EVICTED` with `evicted_reason` `MANUAL`.

The accessibility pipeline runs parallel to seating. A graduate files an accommodation request naming the `ceremony_id`, a `request_type` of `WHEELCHAIR_SEAT`, `SIGN_INTERPRETER`, `ASSISTIVE_LISTENING`, or `SERVICE_ANIMAL`, and optional free-text `notes` (stored as an empty string when omitted); the request stands `SUBMITTED`. The named ceremony is not checked to be the graduate's own. A `VenueCoordinator` approves or denies from `SUBMITTED`. Approval of a `WHEELCHAIR_SEAT` request consumes the accessible pool: it is permitted only while the count of that ceremony's `WHEELCHAIR_SEAT` requests already in `APPROVED` or `FULFILLED` remains below the effective venue's `accessible_capacity`, else it is rejected with `ERR_ACCESSIBLE_CAPACITY_EXCEEDED`; a successful approval records the caller as `approved_by_user_id`. Denial — optionally annotated with a `reason` that is accepted but not stored — is terminal. Fulfillment moves an `APPROVED` request to the terminal `FULFILLED` and, per §2.7, must be performed by a different coordinator than the approver: the caller's identifier must differ from `approved_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`, and the fulfiller is recorded as `fulfilled_by_user_id`.

The rain plan is the weather dimension's teeth. While the ceremony stands in `AUDIT_LOCKED` or `READY` — any other posture is `ERR_CEREMONY_POSTURE_FORBIDS` — a `VenueCoordinator` may flip `weather_mode` from `FAIR` to `RAIN_PLAN_ACTIVE`. Activation requires a designated rain venue (a null `rain_venue_id` is `ERR_RAIN_VENUE_MISSING`) and requires the ceremony's reserved accessible inventory — the count of `APPROVED` or `FULFILLED` `WHEELCHAIR_SEAT` requests — to fit within the rain venue's `accessible_capacity` (else `ERR_ACCESSIBLE_CAPACITY_EXCEEDED`); per the global order of §2.11, the accessible-pool comparison is evaluated before the missing-venue check. Activation then recomputes the pools with the rain venue's `total_capacity` as the new `effective_capacity`, and if the rain venue is smaller, the chart shrinks by force: while the count of `ASSIGNED` seats exceeds the new `effective_capacity`, seats are evicted in a fixed selector order — non-accessible seats before accessible ones, then higher `row_label` values first (labels that parse as integers compare numerically; all other labels compare lexicographically), then higher `seat_number` values first, then most recently created first — each eviction moving the seat to `EVICTED` with `evicted_reason` `RAIN_SHRINK` and raising `open_seat_count` by one. With the chart reconciled, the FINAL ticket waterfall re-runs under the shrunken pool: grants may shrink, `WAITLISTED` and `PARTIAL` allocations are reassigned, and `ticket_pool_remaining` is recomputed. The ceremony's `version` increments.

Deactivation is asymmetric by design. Flipping `RAIN_PLAN_ACTIVE` back to `FAIR` — again only in `AUDIT_LOCKED` or `READY` — restores the primary venue's `total_capacity` as `effective_capacity` and grows `open_seat_count`, but evicted seats are **not** restored: a seat evicted by the rain shrink stays `EVICTED`, and the graduate returns to the unseated candidate pool for a future manual placement or seating sweep. The larger pool does, however, re-run the FINAL ticket waterfall, whose promotion scan pushes the freed tickets into the waitlist in waterfall order. The ceremony's `version` increments here as well.

### 3.6. Reader Cards, Rehearsal Sessions, and the Conduct Policy

Two ceremony-eve concerns share this section: getting every name pronounced correctly, and getting every graduate through rehearsal with their walk privilege intact.

Each graduate may file exactly one reader card. Submission carries the `phonetic_spelling` of the graduate's name for the name reader, requires the graduate to pass the eligibility gate of §2.11 (else `ERR_GRADUATE_NOT_ELIGIBLE`), must arrive no later than the ceremony's `pronunciation_deadline` (strictly after is `ERR_PRONUNCIATION_DEADLINE_PASSED`), and is refused outright if a card already exists for the graduate (`ERR_READER_CARD_EXISTS`). The card starts `SUBMITTED` with a null `approved_by_user_id`. While it remains `SUBMITTED`, the graduate may revise the `phonetic_spelling` — each revision incrementing the card's `version`; editing a card in any other status is `ERR_INVALID_STATE` — and a `CommitteeChair` may approve it, moving it to `APPROVED` and stamping `approved_by_user_id` with the approver. Neither state is final: when the ceremony is marked ready (§3.1), every `SUBMITTED` and `APPROVED` card for the ceremony's graduates locks to the terminal `LOCKED`, freezing the pronunciation record for the ceremony.

Rehearsals are venue bookings with an overlap rule. A `VenueCoordinator` books a session by naming the `venue_id`, a `start_utc`, an `end_utc` strictly after the start, and a `capacity` of at least one registered attendee. Sessions at the same venue are treated as half-open intervals: a new `SCHEDULED` session conflicts with an existing `SCHEDULED` session at that venue only when their windows truly intersect, and back-to-back sessions — one's `end_utc` equal to the other's `start_utc` — are allowed; a genuine overlap is rejected with `ERR_VENUE_TIME_OVERLAP`. A new session stands `SCHEDULED` with `registered_count` zero.

Graduates register themselves for a session while they pass the eligibility gate (else `ERR_GRADUATE_NOT_ELIGIBLE`); the gate runs against the caller's own graduate record resolved from `X-User-ID` — a caller with no such record is rejected with `ERR_NOT_FOUND` — and fires before the check that the session still stands `SCHEDULED` (else `ERR_INVALID_STATE`). The session's ceremony is not checked against the graduate's own ceremony. Registration is refused when the graduate already holds a `REGISTERED` or `ATTENDED` attendance for that session (`ERR_DUPLICATE_REGISTRATION`) and when the count of the session's `REGISTERED` and `ATTENDED` attendances has reached its `capacity` (`ERR_REHEARSAL_FULL`). A successful registration creates the attendance in `REGISTERED` status — its `rehearsal_session_id` pointing at the session and its `graduate_id` taken from the caller's own identity — and raises the session's `registered_count` by one. On the day, a `VenueCoordinator` checks a `REGISTERED` graduate in while the session is still `SCHEDULED`, moving the attendance to `ATTENDED` and stamping `checked_in_at` with the current instant.

Completion is where conduct bites. When a `VenueCoordinator` completes a `SCHEDULED` session, every attendance still `REGISTERED` flips to `ABSENT` with `recorded_by_user_id` set to the completing coordinator, and each such absence adds one to the graduate's `conduct_strike_count`; the session's `registered_count` is left unchanged by completion. Cancelling a `SCHEDULED` session is the gentle path: its `REGISTERED` attendances move to `CANCELLED`, no strikes are recorded, and `registered_count` is recomputed as the count of its remaining `REGISTERED` and `ATTENDED` attendances. An absence can later be excused: a `VenueCoordinator` waives an `ABSENT` attendance to `EXCUSED`, which subtracts one from the graduate's `conduct_strike_count` and stamps `waived_by_user_id` — but per §2.7 the waiving coordinator must differ from the coordinator who recorded the absence, else `ERR_SEGREGATION_OF_DUTIES`.

The strike ledger drives one hard consequence. A graduate's `conduct_strike_count` counts their `ABSENT` attendances across the ceremony's sessions — `CANCELLED`, `EXCUSED`, `ATTENDED`, and `REGISTERED` attendances never count — and `walk_privilege_revoked` becomes true the moment the count reaches at least two: exactly two unexcused strikes already revokes. When the ceremony's `rehearsal_required` flag is set (its default), this revocation is enforced where it hurts: regalia fulfillment in §3.4 refuses a revoked graduate with `ERR_WALK_PRIVILEGE_REVOKED`. Every strike addition and every waiver recomputes the flag; such recomputation refreshes the graduate's `updated_at` but does not increment the graduate's `version`.

### 3.7. Diploma Printing, Issuance, and Post-Ceremony Correction

Diplomas are produced in batches, and the batch is the unit of release control. A `RegistrarOfficer` opens a print batch for a ceremony — optionally noting a `scheduled_print_date` — and the batch stands `OPEN` with the creator recorded as `created_by_user_id` and a `diploma_count` of zero. Queuing a diploma attaches it to an `OPEN` batch: the officer names the `graduate_id` and optionally a `printed_name`, which defaults to the graduate's `full_name` when omitted. Queueing requires the ceremony posture to be `AUDIT_LOCKED` or `READY` (else `ERR_CEREMONY_POSTURE_FORBIDS`) and the graduate to pass the eligibility gate (else `ERR_GRADUATE_NOT_ELIGIBLE`). At the instant of queueing, the diploma pins the graduate's **current** `honor_tier` into `pinned_honor_tier`, derives its `honors_text` from that pinned tier — the empty string for `NONE`, otherwise the lowercase Latin phrase `cum laude`, `magna cum laude`, or `summa cum laude` — and stands `QUEUED`; the batch's `diploma_count` rises by one and the batch's `version` increments with it. Queueing enforces no uniqueness — a graduate may hold any number of queued diplomas — and the graduate is not checked to belong to the batch's ceremony. This pinning is deliberate: the diploma's Latin honors are a snapshot, and the snapshot's freshness is checked at release time rather than assumed.

Release is the scrutinized step, and its checks fire in the order of §2.11. The batch must be `OPEN` (else `ERR_INVALID_STATE`); the releasing `RegistrarOfficer` must differ from the batch's `created_by_user_id` (else `ERR_SEGREGATION_OF_DUTIES`); the ceremony posture must be `AUDIT_LOCKED`, `READY`, `COMMENCED`, or `COMPLETED` — post-ceremony correction reprints must remain releasable — else `ERR_CEREMONY_POSTURE_FORBIDS`; the batch must hold at least one diploma (an empty batch is `ERR_BATCH_NOT_RELEASABLE`); and every attached diploma in `QUEUED` or `REPRINT_QUEUED` must carry a `pinned_honor_tier` equal to its graduate's **current** `honor_tier` — a mismatch, typically created by an audit reopening or a grade revision after queueing, is rejected with `ERR_HONOR_SNAPSHOT_STALE`, which is the intended serialization point between honor recomputation and printing. A clean release moves the batch to `RELEASED` and stamps `released_by_user_id` with the releaser. Marking the batch printed moves `RELEASED` to the terminal `PRINTED` and cascades every attached diploma in `QUEUED` or `REPRINT_QUEUED` to `PRINTED`.

Issuance happens at the ceremony itself: a `CommitteeChair` issues a `PRINTED` diploma — only while the ceremony's posture is `COMMENCED`, else `ERR_CEREMONY_POSTURE_FORBIDS` — moving it to `ISSUED`.

The correction cycle handles the misspelled sheepskin. Within thirty days of the ceremony's `ceremony_date` — strictly later is `ERR_CORRECTION_WINDOW_CLOSED` — the graduate requests a correction on an `ISSUED` diploma by supplying the `corrected_name`; the diploma moves to `CORRECTION_REQUESTED` with the requested name stored on `corrected_name`. A `RegistrarOfficer` then decides with a `decision` value, and both branches require the diploma to stand in `CORRECTION_REQUESTED`. Approval requires an `OPEN` print batch to exist for the ceremony (else `ERR_NO_OPEN_REPRINT_BATCH`); it reassigns the diploma's `print_batch_id` to that open batch — the earliest-created open batch when several stand open — copies `corrected_name` into `printed_name`, clears `corrected_name` to null, adds one to `correction_count`, re-pins `honors_text` and `pinned_honor_tier` from the graduate's **current** `honor_tier`, and moves the diploma to `REPRINT_QUEUED` — from which the next batch printing returns it to `PRINTED`, ready to be issued again. Both the vacated and the receiving batch have their `diploma_count` recomputed as the number of diplomas now attached to them (of any status), without their `version`s incrementing. Denial clears `corrected_name` to null and returns the diploma to `ISSUED`. Withdrawal, per §3.9, archives diplomas still in `QUEUED` or `REPRINT_QUEUED` while leaving `PRINTED` and `ISSUED` diplomas untouched.

### 3.8. Vendor Contracts, Deliverables, and Cancellation

Livestream and photography coverage is contracted per ceremony. A `CommitteeChair` creates a contract naming the `vendor_type` — `LIVESTREAM` or `PHOTOGRAPHY` — the `vendor_user_id` of the external operator who will be allowed to submit the deliverable, a `coverage_start_utc` and `coverage_end_utc` with the end strictly after the start, an optional `setup_buffer_minutes` defaulting to 30 and never negative, and a `fee_cents` of at least zero. Double-booking is caught at creation: two contracts for the same ceremony and the same `vendor_type` conflict when their buffered coverage windows overlap, where each window is extended by its `setup_buffer_minutes` on **both** sides and treated as a closed interval — windows that merely touch at a boundary still conflict. Contracts in `CANCELLED` status are ignored by the check, and a genuine overlap is rejected with `ERR_VENDOR_COVERAGE_OVERLAP`. A new contract stands `DRAFT` with a null `deliverable_url` and a null `cancellation_fee_cents`.

Activation moves `DRAFT` to `ACTIVE` and requires the ceremony posture to be `AUDIT_LOCKED`, `READY`, or `COMMENCED` (else `ERR_CEREMONY_POSTURE_FORBIDS`). Once the ceremony has commenced or completed, the contracted `Vendor` submits the deliverable link: submission is accepted only on the vendor's own contracts — the contract's `vendor_user_id` must equal the caller's identity, else `ERR_FORBIDDEN_OWNERSHIP` — and only in `COMMENCED` or `COMPLETED` posture; the contract's own status is not checked, and resubmission overwrites any previous link. Submission sets `deliverable_url` on the contract. Settlement is the chair's sign-off: an `ACTIVE` contract moves to the terminal `SETTLED` only when a `deliverable_url` has been submitted; settling before submission is rejected with `ERR_VENDOR_DELIVERABLE_MISSING`.

Cancellation is priced by timing. The chair may cancel from `DRAFT` or `ACTIVE`, moving the contract to the terminal `CANCELLED` and storing the fee on `cancellation_fee_cents`: cancelling strictly before `coverage_start_utc` costs ten percent of `fee_cents` rounded half up to a whole cent, while cancelling at or after `coverage_start_utc` costs fifty percent rounded half up — the boundary instant itself is charged at the fifty-percent rate. Each activation, submission, settlement, and cancellation increments the contract's `version`.

### 3.9. Withdrawal and Ceremony Completion

Withdrawal is the system's widest cascade, available to a `RegistrarOfficer` or to the graduate themselves from any status except `WITHDRAWN`, and only while the ceremony has not reached `COMPLETED`. Withdrawing a graduate fans out across five aggregates in one atomic gesture:

- The graduate's ticket allocation, unless already `RELEASED` or `EXPIRED`, moves to `RELEASED`: its `granted_count` is credited back to `ticket_pool_remaining` and zeroed, and the release itself fires the promotion scan of §3.3 over the remaining `WAITLISTED` and `PARTIAL` allocations, each promotion decrementing the pool anew.
- Any `ASSIGNED` seat the graduate holds moves to `EVICTED` with `evicted_reason` `WITHDRAWN`, raising `open_seat_count` by one per eviction.
- Any regalia order still `SUBMITTED` moves to `CANCELLED`; orders already `PAID` or `FULFILLED` are untouched.
- Any rehearsal attendance still `REGISTERED` moves to `CANCELLED`, recording no strike; the session's `registered_count` is left unchanged.
- Any diploma still `QUEUED` or `REPRINT_QUEUED` moves to the terminal `ARCHIVED`, and the batch's `diploma_count` is not decremented; diplomas already `PRINTED` or `ISSUED` are untouched.

The graduate's own status settles at the terminal `WITHDRAWN` and their `version` increments by one.

Completion, introduced in §3.1, is the ceremony's final sweep and withdrawal's closing bracket: once the chair completes a `COMMENCED` ceremony, the posture lands at `COMPLETED`, every ticket allocation still `PENDING` or `WAITLISTED` expires to `EXPIRED` with its grant zeroed and its `waitlist_position` cleared, and no further withdrawals or confirmations are accepted.

## 4. Endpoint Definitions

All endpoints are mounted under `/api`. Status codes follow a uniform rule: creating a new resource returns 201; modifications, lifecycle actions, and reads return 200. Requests outside this surface — unknown paths or unsupported methods — are rejected with `ERR_NOT_FOUND` (HTTP 404). Request payloads, preconditions, and side effects for each endpoint are specified in the narratives of §2 and §3; the table below is the index, not the contract.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /api/_clock/set_current_utc | Set the logical clock; before any call the clock reads the fixed default 2026-05-01T00:00:00Z and never falls back to wall-clock time | CommitteeChair, RegistrarOfficer, VenueCoordinator |
| POST | /api/ceremonies | Create ceremony (posture PLANNING, weather FAIR; pools initialized from venue) | CommitteeChair |
| GET | /api/ceremonies/{id} | Read ceremony | CommitteeChair, RegistrarOfficer, VenueCoordinator, Graduate, Vendor |
| PATCH | /api/ceremonies/{id} | Update ceremony configuration (OCC-guarded) | CommitteeChair |
| POST | /api/ceremonies/{id}/open-audit | Move posture PLANNING to AUDIT_OPEN | CommitteeChair |
| POST | /api/ceremonies/{id}/lock-audit | Move posture AUDIT_OPEN to AUDIT_LOCKED; finalizes honor tiers (INSTITUTIONAL variant) | CommitteeChair |
| POST | /api/ceremonies/{id}/reopen-audit | Revert AUDIT_LOCKED to AUDIT_OPEN; blocked while a batch is RELEASED or PRINTED | CommitteeChair |
| POST | /api/ceremonies/{id}/mark-ready | Move AUDIT_LOCKED to READY; requires audits complete and reader cards present; locks reader cards | CommitteeChair |
| POST | /api/ceremonies/{id}/activate-rain-plan | Flip weather FAIR to RAIN_PLAN_ACTIVE; capacity shrink cascades to seats and tickets | VenueCoordinator |
| POST | /api/ceremonies/{id}/deactivate-rain-plan | Flip RAIN_PLAN_ACTIVE back to FAIR; pools grow; promotion scan runs; evicted seats are not restored | VenueCoordinator |
| POST | /api/ceremonies/{id}/commence | Move READY to COMMENCED | CommitteeChair |
| POST | /api/ceremonies/{id}/complete | Move COMMENCED to COMPLETED; expires pending ticket allocations | CommitteeChair |
| POST | /api/ceremonies/{id}/run-ticket-waterfall | Run the FINAL ticket waterfall over the ceremony's non-terminal allocations | CommitteeChair |
| POST | /api/ceremonies/{id}/run-seating | Auto-assign seats to eligible-family graduates per the deterministic seating selector | VenueCoordinator |
| GET | /api/ceremonies/{id}/graduates | List graduates of a ceremony | CommitteeChair, RegistrarOfficer, VenueCoordinator |
| GET | /api/ceremonies/{id}/ticket-allocations | List ticket allocations of a ceremony | CommitteeChair, RegistrarOfficer, VenueCoordinator |
| GET | /api/ceremonies/{id}/seat-assignments | List seat assignments of a ceremony | CommitteeChair, RegistrarOfficer, VenueCoordinator |
| GET | /api/ceremonies/{id}/accommodation-requests | List accommodation requests of a ceremony | CommitteeChair, RegistrarOfficer, VenueCoordinator |
| GET | /api/ceremonies/{id}/vendor-contracts | List vendor contracts of a ceremony | CommitteeChair, VenueCoordinator |
| GET | /api/ceremonies/{id}/print-batches | List print batches of a ceremony | CommitteeChair, RegistrarOfficer |
| GET | /api/ceremonies/{id}/rehearsal-sessions | List rehearsal sessions of a ceremony | CommitteeChair, RegistrarOfficer, VenueCoordinator, Graduate |
| POST | /api/venues | Create venue | VenueCoordinator |
| GET | /api/venues/{id} | Read venue | CommitteeChair, RegistrarOfficer, VenueCoordinator, Graduate, Vendor |
| GET | /api/venues/{id}/ceremonies | List ceremonies using this venue as primary or rain venue | CommitteeChair, RegistrarOfficer, VenueCoordinator |
| GET | /api/venues/{id}/rehearsal-sessions | List rehearsal sessions booked at this venue | CommitteeChair, RegistrarOfficer, VenueCoordinator |
| POST | /api/graduates | Import a graduate record; auto-creates a PENDING ticket allocation | RegistrarOfficer |
| GET | /api/graduates/{id} | Read graduate (Graduate role restricted to self) | CommitteeChair, RegistrarOfficer, VenueCoordinator, Graduate |
| POST | /api/graduates/{id}/withdraw | Withdraw graduate; cascades release, eviction, cancellation, and archival | RegistrarOfficer, Graduate |
| POST | /api/graduates/{id}/confirm | Graduate confirms attendance (ELIGIBLE or ELIGIBLE_ON_APPEAL to CONFIRMED) | Graduate |
| POST | /api/graduates/{id}/grade-revision | Post revised grades while AUDIT_LOCKED; recomputes FINAL honor and may stale queued diploma snapshots | RegistrarOfficer |
| GET | /api/graduates/{id}/audits | List eligibility audits of a graduate (Graduate restricted to self) | CommitteeChair, RegistrarOfficer, VenueCoordinator, Graduate |
| GET | /api/graduates/{id}/ticket-allocations | List ticket allocations of a graduate (zero or one row; Graduate restricted to self) | CommitteeChair, RegistrarOfficer, VenueCoordinator, Graduate |
| GET | /api/graduates/{id}/regalia-orders | List regalia orders of a graduate (Graduate restricted to self) | CommitteeChair, RegistrarOfficer, VenueCoordinator, Graduate |
| GET | /api/graduates/{id}/seat-assignments | List seat assignments of a graduate (Graduate restricted to self) | CommitteeChair, RegistrarOfficer, VenueCoordinator, Graduate |
| GET | /api/graduates/{id}/diplomas | List diplomas of a graduate (Graduate restricted to self) | CommitteeChair, RegistrarOfficer, VenueCoordinator, Graduate |
| GET | /api/graduates/{id}/accommodation-requests | List accommodation requests of a graduate (Graduate restricted to self) | CommitteeChair, RegistrarOfficer, VenueCoordinator, Graduate |
| GET | /api/graduates/{id}/rehearsal-attendances | List rehearsal attendances of a graduate (Graduate restricted to self) | CommitteeChair, RegistrarOfficer, VenueCoordinator, Graduate |
| GET | /api/graduates/{id}/reader-cards | List reader cards of a graduate (zero or one row; Graduate restricted to self) | CommitteeChair, RegistrarOfficer, VenueCoordinator, Graduate |
| POST | /api/graduates/{id}/audits | Run an eligibility audit; computes the result and the provisional COMBINED honor | RegistrarOfficer |
| POST | /api/eligibility-audits/{id}/appeal | Graduate appeals a FAIL audit within fourteen days | Graduate |
| POST | /api/eligibility-audits/{id}/appeal-decision | CommitteeChair decides an appeal | CommitteeChair |
| POST | /api/ticket-allocations/{id}/request | Request guest tickets; supersedes prior request terms; OCC-guarded | Graduate |
| POST | /api/ticket-allocations/{id}/release | Release granted tickets back to the pool; triggers the promotion scan | Graduate |
| POST | /api/graduates/{id}/regalia-orders | Submit a regalia order; pricing computed at creation; late fee after the regalia order deadline | Graduate |
| GET | /api/regalia-orders/{id} | Read regalia order (Graduate restricted to own) | CommitteeChair, RegistrarOfficer, VenueCoordinator, Graduate |
| POST | /api/regalia-orders/{id}/pay | Pay the exact order total | Graduate |
| POST | /api/regalia-orders/{id}/fulfill | Distribute regalia (PAID or EXCHANGE_REQUESTED to FULFILLED); blocked when walk privilege is revoked | CommitteeChair |
| POST | /api/regalia-orders/{id}/request-exchange | Move FULFILLED to EXCHANGE_REQUESTED (size-exchange loop) | Graduate |
| POST | /api/regalia-orders/{id}/cancel | Cancel a SUBMITTED order (pre-payment only) | Graduate |
| POST | /api/seat-assignments | Manually assign a seat (uniqueness, capacity, and accessible pool enforced) | VenueCoordinator |
| GET | /api/seat-assignments/{id} | Read seat assignment | CommitteeChair, RegistrarOfficer, VenueCoordinator, Graduate |
| POST | /api/seat-assignments/{id}/evict | Manually evict an assigned seat (reason MANUAL) | VenueCoordinator |
| POST | /api/graduates/{id}/reader-card | Submit the pronunciation reader card (one per graduate; before the pronunciation deadline) | Graduate |
| PATCH | /api/reader-cards/{id} | Update the phonetic spelling while SUBMITTED | Graduate |
| POST | /api/reader-cards/{id}/approve | Approve a reader card | CommitteeChair |
| POST | /api/ceremonies/{id}/print-batches | Create an OPEN print batch | RegistrarOfficer |
| GET | /api/print-batches/{id} | Read print batch | CommitteeChair, RegistrarOfficer |
| POST | /api/print-batches/{id}/diplomas | Queue a diploma into an OPEN batch; pins the honor snapshot from the graduate's current tier | RegistrarOfficer |
| GET | /api/print-batches/{id}/diplomas | List diplomas in a batch | CommitteeChair, RegistrarOfficer |
| POST | /api/print-batches/{id}/release | Release a batch to the printer (segregation of duties; honor snapshots must be fresh; posture-gated) | RegistrarOfficer |
| POST | /api/print-batches/{id}/mark-printed | Move RELEASED to PRINTED; attached QUEUED and REPRINT_QUEUED diplomas move to PRINTED | RegistrarOfficer |
| GET | /api/diplomas/{id} | Read diploma (Graduate restricted to own) | CommitteeChair, RegistrarOfficer, VenueCoordinator, Graduate |
| POST | /api/diplomas/{id}/issue | Issue a printed diploma at the ceremony (posture COMMENCED) | CommitteeChair |
| POST | /api/diplomas/{id}/corrections | Graduate requests a name correction within thirty days after the ceremony date | Graduate |
| POST | /api/diplomas/{id}/correction-decision | Approve (requires an OPEN batch; re-pins the honor snapshot) or deny a correction | RegistrarOfficer |
| POST | /api/ceremonies/{id}/rehearsal-sessions | Book a rehearsal session at a venue (half-open overlap check) | VenueCoordinator |
| GET | /api/rehearsal-sessions/{id} | Read rehearsal session | CommitteeChair, RegistrarOfficer, VenueCoordinator, Graduate |
| POST | /api/rehearsal-sessions/{id}/register | Graduate registers for a session (creates a REGISTERED attendance) | Graduate |
| POST | /api/rehearsal-sessions/{id}/complete | Complete a session; no-shows become ABSENT strikes recorded by the caller | VenueCoordinator |
| POST | /api/rehearsal-sessions/{id}/cancel | Cancel a session; registrations are CANCELLED without strikes | VenueCoordinator |
| GET | /api/rehearsal-sessions/{id}/attendances | List attendances of a session | CommitteeChair, RegistrarOfficer, VenueCoordinator |
| POST | /api/rehearsal-attendances/{id}/check-in | Check in a registered graduate while the session is still SCHEDULED | VenueCoordinator |
| POST | /api/rehearsal-attendances/{id}/waive | Excuse an absence (segregation of duties: caller differs from the recorder); strike removed | VenueCoordinator |
| POST | /api/graduates/{id}/accommodation-requests | Submit an accessibility accommodation request | Graduate |
| GET | /api/accommodation-requests/{id} | Read accommodation request (Graduate restricted to own) | CommitteeChair, RegistrarOfficer, VenueCoordinator, Graduate |
| POST | /api/accommodation-requests/{id}/approve | Approve a request (WHEELCHAIR_SEAT consumes the accessible-seat pool) | VenueCoordinator |
| POST | /api/accommodation-requests/{id}/deny | Deny a request | VenueCoordinator |
| POST | /api/accommodation-requests/{id}/fulfill | Mark a request fulfilled (segregation of duties: caller differs from the approver) | VenueCoordinator |
| POST | /api/ceremonies/{id}/vendor-contracts | Contract a livestream or photography vendor (buffered closed-interval overlap check per vendor type) | CommitteeChair |
| GET | /api/vendor-contracts/{id} | Read vendor contract | CommitteeChair, VenueCoordinator, Vendor |
| POST | /api/vendor-contracts/{id}/activate | Move DRAFT to ACTIVE (posture AUDIT_LOCKED, READY, or COMMENCED) | CommitteeChair |
| POST | /api/vendor-contracts/{id}/submit-deliverable | Vendor submits the deliverable (own contracts only; ceremony COMMENCED or COMPLETED) | Vendor |
| POST | /api/vendor-contracts/{id}/settle | Settle an ACTIVE contract with a submitted deliverable | CommitteeChair |
| POST | /api/vendor-contracts/{id}/cancel | Cancel a DRAFT or ACTIVE contract; cancellation fee computed from time versus coverage start | CommitteeChair |

## 5. Error Code Catalogue

Trigger conditions for each error live in the narratives of §2 and §3; this table is the identifier index.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED_ROLE | 403 |
| ERR_FORBIDDEN_OWNERSHIP | 403 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_CEREMONY_POSTURE_FORBIDS | 409 |
| ERR_GRADUATE_NOT_ELIGIBLE | 409 |
| ERR_WALK_PRIVILEGE_REVOKED | 409 |
| ERR_REQUEST_WINDOW_CLOSED | 422 |
| ERR_PRONUNCIATION_DEADLINE_PASSED | 422 |
| ERR_APPEAL_WINDOW_CLOSED | 422 |
| ERR_CORRECTION_WINDOW_CLOSED | 422 |
| ERR_TICKET_CAP_EXCEEDED | 422 |
| ERR_PAYMENT_AMOUNT_MISMATCH | 402 |
| ERR_SEAT_CONFLICT | 409 |
| ERR_SEAT_CAPACITY_EXCEEDED | 422 |
| ERR_ACCESSIBLE_CAPACITY_EXCEEDED | 422 |
| ERR_VENUE_TIME_OVERLAP | 409 |
| ERR_VENDOR_COVERAGE_OVERLAP | 409 |
| ERR_VENDOR_DELIVERABLE_MISSING | 409 |
| ERR_RAIN_VENUE_MISSING | 409 |
| ERR_HONOR_SNAPSHOT_STALE | 409 |
| ERR_NO_OPEN_REPRINT_BATCH | 409 |
| ERR_BATCH_NOT_RELEASABLE | 409 |
| ERR_READER_CARD_EXISTS | 409 |
| ERR_REHEARSAL_FULL | 422 |
| ERR_DUPLICATE_REGISTRATION | 409 |
