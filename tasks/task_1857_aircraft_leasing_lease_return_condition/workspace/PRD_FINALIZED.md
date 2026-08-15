# Aircraft Leasing Returns API — Product Requirements Document

## 1. Introduction

Commercial aircraft lessors live and die by the quality of their paper trail. A widebody airframe changes operators several times over its economic life, and each handover exposes the lessor to the same risks: maintenance reserves that were collected but not properly accounted for, records that fail back-to-birth traceability when the next lessee's auditors arrive, redelivery condition disputes that drag on for months, and obligors whose credit deteriorates mid-term. The system described here is the operational backbone for a lessor's asset-management team: it tracks every aircraft from registration through lease activation, monthly utilization accrual, reserve reimbursement, return-condition negotiation, settlement, and transition to the next operator — including the unhappy paths of default and repossession.

This document specifies the Aircraft Leasing Returns API, mounted under the `/leasing` path prefix. It covers the lease term and rent/utilization structure, maintenance-reserve accrual per flight hour and flight cycle, the return-condition checklist and compensation negotiation workflow, records-completeness gating, the technical inspection at redelivery with booked certifying staff, sub-lease and novation approval under segregation of duties, the default and repossession process, and transition-slot scheduling for the next lessee. The audience is the engineering team building the service; every behavioral rule below is normative.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity in which they act. The system recognizes six roles, spelled exactly as follows: `LessorAdmin`, `LesseeRep`, `TechInspector`, `CreditOfficer`, `LegalApprover`, and `FinanceManager`. A request whose role header is missing, or names a value outside this set, or whose user header is missing, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is valid but not on the endpoint's authorized list — or that fails an entity-backed ownership check described below — is rejected with `ERR_FORBIDDEN` (HTTP 403).

The identity carried by `X-User-ID` differs by role, and the distinction is contractual:

- When `X-User-Role` is `LesseeRep`, `X-User-ID` is the `id` of the acting `Lessee`; ownership checks on any resource reached through a lease compare the lease's `lessee_id` field to `X-User-ID`, and acting on another lessee's lease is `ERR_FORBIDDEN`.
- When `X-User-Role` is `TechInspector`, `X-User-ID` is the `id` of the acting `Inspector`; the inspection booking gate compares a booking's `inspector_id` to `X-User-ID`.
- When `X-User-Role` is `LessorAdmin`, `CreditOfficer`, `LegalApprover`, or `FinanceManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `credit_reviewed_by`, `legal_reviewed_by`, or `declared_by` where a workflow stamps the acting officer — but never compares it to any entity's `id`.

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

### 2.3. Pagination and List Ordering

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless a list endpoint states a more specific ordering in §3, all list endpoints return resources sorted by `created_at` in ascending order. Transition slots are instead ordered by `window_start` ascending with `created_at` ascending as the tie-break; inspection bookings are ordered by `booking_date` ascending with `created_at` ascending as the tie-break; a return case's checklist items are ordered by `item_code` ascending (which yields `AIRFRAME`, `ENGINE`, `INTERIOR`, `PAINT`); and a lease's utilization reports are ordered by `period_month` ascending.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

Every date-dependent rule in the system — cure deadlines on default cases, the inspection booking gate, transition-slot window arithmetic — reads a single server-side logical clock, never the host's wall clock. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and the server must never fall back to wall-clock time. A `LessorAdmin` may set the logical clock by supplying a `to_iso8601` instant; the capability responds with the new `current_utc`. Tests and operators rely on this determinism: two runs against the same clock inputs must produce identical accept/reject outcomes.

### 2.5. Common Resource Properties

All primary resources in the system — aircraft, lessees, inspectors, leases, utilization reports, reserve claims, aircraft documents, return cases, checklist items, novation requests, default cases, and transition slots — carry a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set when the resource is created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version` (integer): a system-managed integer that increments by one with every modification of the resource, including cascaded mutations originating from another entity's transition.

The single exception is the **inspection booking**, which is a scheduling record rather than a mutable resource: it carries `id` and `created_at` only, and both `updated_at` and `version` are absent from it.

### 2.6. Monetary Precision and Rounding

All monetary amounts in the system are integer cents. Every stored money field — `monthly_rent_cents`, `reserve_rate_per_fh_cents`, `reserve_rate_per_fc_cents`, the reserve ledger fields, claim amounts, proposal amounts, and settlement amounts — is an exact integer count of cents; the API never emits fractional cents. Where a calculation multiplies a decimal quantity by a cent rate (the flight-hour accrual term, each overage tier, each severity-weighted checklist line), the product is rounded half up to whole cents, and the rounding points are pinned per calculation in §3: the accrual applies rounding once to the flight-hour term only, the monthly charge applies it per overage tier before summation, and the provisional compensation estimate applies it per checklist line before summation. Flight hours are carried to one decimal place; flight cycles are integers.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and only those two accept a version field; no other endpoint takes one.

Amending a lease requires the request to carry `expected_lease_version`, equal to the lease's `version` the client last observed. If the lease's current `version` has advanced — whether by a prior amendment or by any cascade that bumped it, such as activation or a novation reassignment — the write is refused with `ERR_STALE_VERSION` (HTTP 412) rather than silently layered over a state the client never saw.

Recording agreement on a return case requires the request to carry `expected_return_case_version`, equal to the return case's `version` the client last observed. If the case's `version` has advanced — for example because a further proposal round or a re-inspection loop superseded the standing proposal — the agreement is rejected with `ERR_STALE_VERSION` (HTTP 412), since it would otherwise bind terms the counterparty never saw.

### 2.8. Validation Order and Nested Resource Retrieval

Every request is evaluated against a fixed validation pipeline, and the order is normative because several rules can fail simultaneously. The pipeline runs:

1. **Authentication** — both headers present, role declared (else `ERR_UNAUTHENTICATED`).
2. **Authorization and ownership** — the acting role is on the endpoint's list, and for entity-backed ownership endpoints the `X-User-ID` equals the owning entity's `id` (else `ERR_FORBIDDEN`).
3. **Path existence** — every identifier in the URL resolves, validated strictly left to right; the first identifier that does not resolve yields `ERR_NOT_FOUND` (HTTP 404) and no later segment is examined. A request for a utilization report under a non-existent lease therefore fails on the lease before the report is ever considered.
4. **Request well-formedness** — required fields present, enum values within their declared sets, numeric ranges respected, `end_date` strictly after `start_date`, `window_end` on or after `window_start`, and a proposed novation counterparty that differs from the current lessee (else `ERR_INVALID_REQUEST`, HTTP 400).
5. **State preconditions** — the target resource is in a from-state the transition allows, including terminal-state lockdown and the one-open-child rules (else `ERR_INVALID_STATE`, HTTP 409; a claim payment attempted on a claim not `APPROVED` instead yields `ERR_CLAIM_NOT_PAYABLE`).
6. **Records safety gates** — the document-completeness gates on lease activation and records review (else `ERR_RECORDS_INCOMPLETE`).
7. **Temporal rules** — lease-period overlap, slot-window buffering, and cure-deadline checks (else `ERR_LEASE_PERIOD_OVERLAP`, `ERR_SLOT_WINDOW_CONFLICT`, or `ERR_CURE_DEADLINE_NOT_PASSED` respectively).
8. **Business constraints** — inspector day-capacity, report-period uniqueness, the checklist gate, negotiation alternation, the re-inspection cap, segregation of duties, and the inspection booking gate (the last of these carries `ERR_BOOKING_REQUIRED`, HTTP 403).
9. **Cross-entity referential state** — aircraft availability, lessee standing, and open-default-case checks (else `ERR_AIRCRAFT_NOT_AVAILABLE`, `ERR_LESSEE_NOT_ACTIVE`, or `ERR_DEFAULT_CASE_OPEN`).
10. **Fiscal rules** — reserve-balance sufficiency and approved-amount range checks (else `ERR_RESERVE_BALANCE_EXCEEDED`, HTTP 422, or `ERR_INVALID_REQUEST`).

Where several of these guards attach to one endpoint, the same relative order holds: activation evaluates the records gate before the overlap rule, and the overlap rule before the aircraft-availability and lessee-standing checks; advancing a return case evaluates the records gate before the checklist gate; creating a transition slot evaluates the window-buffer rule before the open-default-case rule; and paying a claim evaluates the payable-state check before the balance check.

### 2.9. Ledger Integrity and Cascading Consistency

Each lease maintains a maintenance-reserve ledger expressed in four fields. `reserve_accrued_cents` is the cumulative reserve accrued from accepted utilization reports; `reserve_reimbursed_cents` is the cumulative reserve paid out through claims that reached `PAID`; `reserve_forfeited_cents` is the reserve remainder forfeited to the lessor at settlement; and `reserve_balance_cents` is a derived invariant, always equal to `reserve_accrued_cents` minus `reserve_reimbursed_cents` minus `reserve_forfeited_cents`. Every event that touches one of the three source fields recomputes the balance in the same atomic mutation, so the invariant holds after every API call until the lease settles. Settlement (§3.6) is the single pinned exception: its fifth step zeroes `reserve_balance_cents` outright rather than recomputing it from the sources — the applied portion leaves the ledger through settlement — so once a lease has settled, the balance remains zero and the derived equality is no longer guaranteed to hold. Reversals are compensating actions, not deletions: voiding an accepted report subtracts exactly the accrual it posted, and reversing a claim payment subtracts exactly the amount that was paid out.

State changes propagate across entity boundaries without a separate client call. When a transition's side effects reach a parent or sibling resource — an airframe going on lease, a lease handed back at settlement, transition slots released by a repossession — the server performs those mutations itself, in the same operation. Each reconciled resource has its own `updated_at` refreshed and its own `version` incremented, so an observer holding a stale `version` for any cascaded entity will fail a subsequent optimistic-concurrency check against it.

## 3. Business Logic & Workflows

### 3.1. Registering the Fleet, Operators, and Certifying Staff

A `LessorAdmin` registers each airframe by supplying its `msn` — the manufacturer serial number, unique across all aircraft — together with the `model` designation (for example A320-200) and the `manufacture_date`, an ISO calendar date that anchors the start of the back-to-birth records horizon. A newly registered aircraft begins life with `status` `AVAILABLE` and with both computed utilization counters, `total_flight_hours` and `total_flight_cycles`, at zero.

Operators are registered in the same administrative motion. A lessee is created with its `legal_name` and an optional `credit_tier` of `A`, `B`, or `C` — `B` when the field is omitted — and starts with `status` `ACTIVE`. Certifying staff are registered as inspectors with a `full_name` and a `license_number`, the latter unique across all inspectors.

Records custody lives on the airframe. A `LessorAdmin` submits a document against an aircraft with a `doc_type` drawn from `BIRTH_RECORD`, `AIRWORTHINESS_CERT`, `ENGINE_LOG`, `LLP_STATUS`, or `OTHER`, plus a free-text `doc_reference`; the document begins in `SUBMITTED`. Reviewing a document with a `decision` of `VERIFIED` or `REJECT` moves it to `VERIFIED` or `REJECTED` respectively, both terminal, and only a `SUBMITTED` document can be reviewed at all — anything else is `ERR_INVALID_STATE`. The aircraft detail read surfaces, alongside the computed totals, a records-completeness score: the number of the four required types — `BIRTH_RECORD`, `AIRWORTHINESS_CERT`, `ENGINE_LOG`, `LLP_STATUS` — for which the aircraft holds at least one `VERIFIED` document, divided by four. A score below exactly 1.0 means the records base is incomplete, and two safety gates downstream depend on that completeness (§3.2 and §3.5).

### 3.2. Lease Origination, Amendment, and Activation

A `LessorAdmin` drafts a lease by naming the airframe through `aircraft_id` and the obligor through `lessee_id`, then fixing the commercial terms: `start_date` and `end_date` describing a half-open interval that includes the start date and excludes the end date; `monthly_rent_cents`, which must be greater than zero; `reserve_rate_per_fh_cents` and `reserve_rate_per_fc_cents`, the maintenance-reserve rates per flight hour and per flight cycle, each zero or greater; and `monthly_hour_cap`, the included flight hours per month before overage tiers apply, which must be greater than zero. The `accrual_basis` selects the reserve-accrual variant — `ACTUAL`, the default, or `MINIMUM_GUARANTEE` — and `minimum_monthly_hours`, defaulting to zero, sets the minimum billable hours per month that apply only when the basis is `MINIMUM_GUARANTEE`. The lease is born in `DRAFT`; its reserve ledger fields start at zero and `approved_sublessee_id` starts null. No overlap checking happens at creation time — two drafts may coexist; the conflict is enforced at activation.

While a lease is in `DRAFT` or `ACTIVE`, a `LessorAdmin` may amend its terms. The amendment is OCC-guarded per §2.7 — the request must carry `expected_lease_version`, and a mismatch with the lease's current `version` is `ERR_STALE_VERSION` — and may touch `monthly_rent_cents`, `reserve_rate_per_fh_cents`, `reserve_rate_per_fc_cents`, `monthly_hour_cap`, `minimum_monthly_hours`, and `end_date`. A successful amendment increments the lease's `version` by one.

Activation is the lease's first hard gate. Moving a `DRAFT` lease to `ACTIVE` requires, evaluated in the pipeline order of §2.8: the aircraft holds at least one `VERIFIED` document of `doc_type` `BIRTH_RECORD` — the back-to-birth anchor, without which the attempt fails with `ERR_RECORDS_INCOMPLETE`; no other lease on the same aircraft in `DRAFT`, `ACTIVE`, `RETURN_INITIATED`, or `DEFAULTED` has a half-open interval intersecting this lease's interval — adjacency, where one lease's `start_date` equals the other's `end_date`, is explicitly permitted, and a true intersection fails with `ERR_LEASE_PERIOD_OVERLAP`; the aircraft's `status` is `AVAILABLE`, else `ERR_AIRCRAFT_NOT_AVAILABLE`; and the lessee's `status` is `ACTIVE`, else `ERR_LESSEE_NOT_ACTIVE`. A lease not in `DRAFT` cannot be activated at all (`ERR_INVALID_STATE`). On success the cascade flips the aircraft from `AVAILABLE` to `ON_LEASE`, refreshing the aircraft's `updated_at` and incrementing its `version`, and increments the lease's own `version`.

### 3.3. Utilization Reporting and the Maintenance Reserve Ledger

Once a lease is running, the lessee's representative reports monthly utilization. Submitting a report requires the `period_month` in `YYYY-MM` form, the month's `flight_hours` (zero or greater), and the month's `flight_cycles` (an integer, zero or greater); the report lands in `SUBMITTED`. At most one non-`VOIDED` report may exist per lease per `period_month` — a duplicate is `ERR_DUPLICATE_REPORT_PERIOD` — while a voided report frees its month for re-submission.

Each report is filed against its lease and carries that lease's `lease_id`. Review by a `LessorAdmin` takes a `decision` and has two arms. Disputing a report records the supplied `reason` on the report's `dispute_reason` and moves it `SUBMITTED → DISPUTED`. Accepting a report — permitted only while the parent lease is `ACTIVE`, `DEFAULTED`, or `RETURN_INITIATED` — posts the maintenance-reserve accrual. The billable hours depend on the lease's `accrual_basis`: under `ACTUAL` the billable hours are exactly the reported `flight_hours`; under `MINIMUM_GUARANTEE` they are the greater of the reported `flight_hours` and the lease's `minimum_monthly_hours`, diverging from the actual basis exactly when the reported hours fall short of the minimum. The posted accrual equals the flight-hour term — billable hours multiplied by `reserve_rate_per_fh_cents`, rounded half up to whole cents — plus the cycle term — `flight_cycles` multiplied by `reserve_rate_per_fc_cents`, exact integer arithmetic with no rounding. That amount is stamped on the report as `posted_accrual_cents`, added into the lease's `reserve_accrued_cents` with the balance recomputed per §2.9, and the aircraft's `total_flight_hours` and `total_flight_cycles` are increased by the reported `flight_hours` and `flight_cycles` in the same mutation. The aircraft totals are defined over `ACCEPTED` reports across every lease of the airframe — hours carried to one decimal place, cycles as integers — so each accept increments them and each void decrements them.

The dispute path is cyclic: the owning `LesseeRep` may revise a `DISPUTED` report, which replaces its `flight_hours` and `flight_cycles`, clears `dispute_reason` to null, and returns it to `SUBMITTED` for another review. The compensating arm of acceptance is the void: a `LessorAdmin` may void an `ACCEPTED` report while the lease is `ACTIVE`, `DEFAULTED`, or `RETURN_INITIATED`, which subtracts exactly `posted_accrual_cents` from `reserve_accrued_cents`, subtracts the report's hours and cycles from the aircraft totals, recomputes the reserve balance, and leaves the report terminally `VOIDED`. Accept followed by void is a net no-op on both ledgers.

Separately from accrual, a computed read answers "what does this month cost?". Given a `month` in `YYYY-MM` form, the charge uses only the `ACCEPTED` utilization report for that period — `SUBMITTED`, `DISPUTED`, and `VOIDED` reports are excluded, and when no accepted report exists the month's hours and cycles are both zero. Overage hours are the hours in excess of `monthly_hour_cap`, floored at zero. The first fifty overage hours bill at 5,000 cents per hour and any overage beyond fifty hours bills at 7,500 cents per hour, with each tier rounded half up to whole cents before the two are summed. A cycle surcharge of 25,000 cents applies when the month's cycles multiplied by two exceed the month's hours, and is zero otherwise. The response carries `month`, `hours`, `cycles`, `base_rent_cents` (the lease's `monthly_rent_cents`), `overage_cents`, `cycle_surcharge_cents`, and their sum `total_cents`.

### 3.4. Reserve Claims: Reimbursement Against the Ledger

The maintenance reserve funds real work. A `LesseeRep` files a claim against its own lease with a `maintenance_event_ref` pointing at the external maintenance event and a `claimed_amount_cents` greater than zero; the claim begins `SUBMITTED`.

The `decision` rests with a `LessorAdmin`. Approving requires an `approved_amount_cents` that is greater than zero and no more than `claimed_amount_cents` — an out-of-range amount is `ERR_INVALID_REQUEST` — and stamps that amount on the claim, where it had been null until decided, as the claim moves `SUBMITTED → APPROVED`. Rejecting moves the claim `SUBMITTED → REJECTED`, terminally. Acting on a claim no longer `SUBMITTED` is `ERR_INVALID_STATE`.

Payment is finance's job, and it is a two-check door in the order fixed by §2.8: the claim must be `APPROVED` — otherwise `ERR_CLAIM_NOT_PAYABLE` — and the lease's `reserve_balance_cents` must be at least `approved_amount_cents`, with equality explicitly payable; a shortfall is `ERR_RESERVE_BALANCE_EXCEEDED`. Paying moves the claim to `PAID`, adds the approved amount to `reserve_reimbursed_cents`, and recomputes the balance. Should a wire bounce or a payment prove mistaken, a `FinanceManager` may reverse it: the claim returns `PAID → APPROVED`, the approved amount comes back out of `reserve_reimbursed_cents`, and the balance is recomputed. Reversal is unavailable once the lease has reached `RETURNED`, `CLOSED`, or `TERMINATED`, since the ledger is by then final.

### 3.5. The Return Case: Records Review, Booked Inspection, and the Checklist

Handback begins when a `LessorAdmin` initiates the return on an `ACTIVE` lease. At most one non-terminal return case may exist per lease — if one is already open (not `SETTLED` and not `CANCELLED`), the initiation is `ERR_INVALID_STATE`. Initiation flips the lease `ACTIVE → RETURN_INITIATED`, creates the return case in `OPEN` with `round_count` and `reinspection_count` at zero, and generates four checklist items from the fixed return-condition template: `item_code` `AIRFRAME` with `severity` `CRITICAL`, `ENGINE` with `MAJOR`, and `INTERIOR` and `PAINT` with `MINOR`, all in `PENDING`, each item stamped with the case's `return_case_id`. Should the return be called off before any inspection has been booked — that is, while the open case is still `OPEN` or `RECORDS_VERIFIED` — aborting the return flips the lease back `RETURN_INITIATED → ACTIVE` and cascades the open case to `CANCELLED`; once the case has moved past `RECORDS_VERIFIED` the return can no longer be aborted (`ERR_INVALID_STATE`).

Advancing the case is a staged workflow with a gate at each stage, driven by a `LessorAdmin` naming the target with `to`. From `OPEN` to `RECORDS_VERIFIED` the records gate applies: for every one of the four required `doc_type` values — `BIRTH_RECORD`, `AIRWORTHINESS_CERT`, `ENGINE_LOG`, `LLP_STATUS` — the aircraft must hold at least one `VERIFIED` document; all four are required, and three of four fails the gate with `ERR_RECORDS_INCOMPLETE`. From `RECORDS_VERIFIED` to `INSPECTION` no further gate applies beyond the from-state itself.

Physical inspection is appointment-based. A `LessorAdmin` books an inspector for a case by naming the `inspector_id` and a `booking_date` (an ISO calendar date); the booking records the `return_case_id` of the case it serves. capacity is one booking per inspector per calendar date, and a second booking for the same inspector on the same date is `ERR_INSPECTOR_DOUBLE_BOOKED`. The booking itself is the only credential a `TechInspector` needs to inspect: recording an outcome on a checklist item requires the case to be in `INSPECTION`, the item to be in `PENDING` or `RECTIFIED`, and an existing booking whose `inspector_id` equals the acting `X-User-ID` and whose `booking_date` equals the logical clock's current date — with no such booking the inspection is refused with `ERR_BOOKING_REQUIRED` (HTTP 403).

Recording `outcome` `COMPLIANT` moves the item to `COMPLIANT`. Recording `outcome` `NON_COMPLIANT` requires a `rectification_cost_estimate_cents` greater than zero — a non-compliant verdict without a positive estimate is `ERR_INVALID_REQUEST` — stores the estimate on the item, and moves it to `NON_COMPLIANT`. Either way the item's `inspected_by_id` is stamped with the acting inspector's `X-User-ID` as an audit stamp. From there the lessee may rectify: marking the item rectified moves it `NON_COMPLIANT → RECTIFIED`, after which a booked inspector re-inspects it — a passing re-inspection moves it `RECTIFIED → COMPLIANT` and re-stamps `inspected_by_id`, while a failing one moves it back `RECTIFIED → NON_COMPLIANT`, overwrites `rectification_cost_estimate_cents` with the new positive estimate, and the rectify/inspect loop may repeat. Alternatively, a `LessorAdmin` may simply waive a `NON_COMPLIANT` item, optionally recording a `reason`, moving it to `WAIVED`; `COMPLIANT`, `WAIVED`, and `COMPENSATED` are the item's terminal states.

### 3.6. Compensation Negotiation, Agreement, and Settlement Netting

With the inspection complete, the case moves `INSPECTION → NEGOTIATION` — but only once the checklist gate passes: zero items of the case may remain in `PENDING` or `RECTIFIED`, otherwise the advance is refused with `ERR_CHECKLIST_INCOMPLETE`. Entering negotiation computes the provisional compensation estimate: for each checklist item in `NON_COMPLIANT` at that moment, the item's `rectification_cost_estimate_cents` is multiplied by the severity uplift — 1.50 for `CRITICAL`, 1.25 for `MAJOR`, 1.10 for `MINOR` — and each line is rounded half up to whole cents; the sum of those per-line rounded amounts is stored as `provisional_estimate_cents`. Items in `COMPLIANT`, `WAIVED`, or `RECTIFIED` contribute nothing. The estimate is a negotiating anchor, not a verdict.

Negotiation itself is a strict alternation of lump-sum proposals. Before any proposal is tabled, `current_proposal_cents` and `current_proposer_side` are both null. Either a `LessorAdmin` (proposing on the `LESSOR` side) or the owning `LesseeRep` (on the `LESSEE` side) may table a proposal carrying `amount_cents`, which must be zero or greater. The first proposal — when `round_count` is zero — must come from the `LESSOR` side; thereafter the proposing side must differ from `current_proposer_side`, the side that tabled the standing proposal. A proposal out of turn, or a first proposal from the lessee side, fails with `ERR_PROPOSER_ALTERNATION`. Each accepted proposal increments `round_count` by one and overwrites `current_proposal_cents` with the new `amount_cents` and `current_proposer_side` with the proposer's side.

The lessee may force one more look at the aircraft: requesting re-inspection loops the case `NEGOTIATION → INSPECTION`, provided `reinspection_count` is still below the hard cap of one — at the cap the request fails with `ERR_REINSPECTION_LIMIT`. The loop increments `reinspection_count`, conditionally cascades every `NON_COMPLIANT` checklist item back to `PENDING` (items `COMPLIANT`, `WAIVED`, or `COMPENSATED` are untouched), and deliberately preserves `round_count` and both `current_proposal_` fields, so negotiation resumes where it left off.

Agreement is the handshake of the side that did not table the standing proposal: either a `LessorAdmin` or the owning `LesseeRep` may accept, provided at least one proposal exists (`round_count` of one or more) and the agreeing side differs from `current_proposer_side` — a self-accept is `ERR_PROPOSER_ALTERNATION`. The call is OCC-guarded per §2.7: it must carry `expected_return_case_version` matching the case's current `version`, else `ERR_STALE_VERSION`. Agreement captures the standing proposal as `agreed_total_cents` — null until this moment, thereafter the final compensation figure, which generally differs from the provisional estimate for the same items — and moves the case `NEGOTIATION → AGREED`.

Settlement belongs to a `FinanceManager` and is permitted only from `AGREED`. Both `reserve_applied_cents` and `settlement_cash_due_cents` are null until settlement runs. It runs the reserve netting in one pinned order: first the current `reserve_balance_cents` is taken as the balance; second, `reserve_applied_cents` is set to the lesser of that balance and `agreed_total_cents`; third, `settlement_cash_due_cents` is set to `agreed_total_cents` minus `reserve_applied_cents` — the cash the lessee still owes; fourth, the forfeiture is the balance minus `reserve_applied_cents`, added into the lease's `reserve_forfeited_cents`; and fifth, the lease's `reserve_balance_cents` is zeroed. Reordering these steps — say, forfeiting the balance before offsetting it — yields different applied and cash-due figures, so the order above is normative. Settlement then closes out the case's loose ends: every checklist item still `NON_COMPLIANT` cascades to `COMPENSATED`, and every reserve claim of the lease still `SUBMITTED` or `APPROVED` cascades to `REJECTED` while `PAID` claims are left untouched. Finally the handback cascade fires: the lease moves `RETURN_INITIATED → RETURNED`; because that lease is the one currently on the aircraft, the aircraft moves `ON_LEASE → IN_TRANSITION`; and that aircraft change auto-confirms a transition slot — among the aircraft's slots in `TENTATIVE` whose window covers the settle date (window start on or before the date and window end on or after it), the one with the earliest `window_start` wins, ties broken by `created_at` ascending, and if no slot qualifies none is confirmed.

### 3.7. Subleases, Novations, and Lessee Standing

Credit standing is actively managed. A `CreditOfficer` may suspend an `ACTIVE` lessee or reinstate a `SUSPENDED` one by naming the target standing with `to`; each flip increments the lessee's `version`, and any other standing transition is `ERR_INVALID_STATE`. A suspended lessee blocks downstream gates — lease activation and novation final approval both demand an `ACTIVE` counterparty.

A lessee that wants out of — or to share — its obligation files a request on its own lease, selecting a `request_type` of `NOVATION` to reassign the obligor entirely or `SUBLEASE` to obtain authorization for a sublessee, and naming the `proposed_lessee_id`. The proposed counterparty must differ from the lease's current lessee, otherwise `ERR_INVALID_REQUEST`. The request begins `SUBMITTED`.

Approval is a two-stage chain with segregation of duties. The credit stage is performed by a `CreditOfficer` on a `SUBMITTED` request: a `decision` to approve moves it to `CREDIT_APPROVED` and a `decision` to reject moves it to `REJECTED`, and either way the officer's `X-User-ID` is stamped as `credit_reviewed_by`. The legal stage is performed by a `LegalApprover` on a `CREDIT_APPROVED` request: the legal reviewer's `X-User-ID` must differ from `credit_reviewed_by` — the same person approving both stages is `ERR_SOD_VIOLATION` — and for an approval the proposed lessee must still have `status` `ACTIVE`, else `ERR_LESSEE_NOT_ACTIVE`. Legal approval moves the request to `APPROVED`, stamps `legal_reviewed_by`, and takes effect on the lease: for `NOVATION` the lease's `lessee_id` is reassigned to the proposed lessee, while for `SUBLEASE` the lease's `approved_sublessee_id` is set to the proposed lessee, and in both arms the lease's `version` is incremented. Legal rejection instead moves the request to `REJECTED`, still stamping `legal_reviewed_by`. Both `APPROVED` and `REJECTED` are terminal. Because the review endpoint admits both roles and infers the stage from the request's status, an attempt by the wrong role for the current stage — a `LegalApprover` reviewing a `SUBMITTED` request, or a `CreditOfficer` reviewing a `CREDIT_APPROVED` one — is rejected with `ERR_FORBIDDEN`, while a review attempted on a request already in a terminal state is `ERR_INVALID_STATE`.

### 3.8. Default, Repossession, and Transition to the Next Lessee

When an obligor falls behind, a `CreditOfficer` declares default on the lease, supplying a `reason` and a `cure_period_days` of zero or more. The system stamps `declared_at` from the logical clock, computes `cure_deadline` as `declared_at` plus the cure period in days, records the declaring officer's `X-User-ID` as `declared_by`, and opens the case in `DECLARED`. Declaration cascades the lease from `ACTIVE` — or from `RETURN_INITIATED`, if a return was already under way — into `DEFAULTED`. A lease may carry at most one open default case: if a case in `DECLARED` or `REPOSSESSION_AUTHORIZED` already exists, a further declaration is `ERR_INVALID_STATE`.

Two exits exist from `DECLARED`. If the lessee cures, the same credit desk marks the case `CURED`, and the lease compensates back `DEFAULTED → ACTIVE`. If not, a `LegalApprover` authorizes repossession — but only once the logical clock reads strictly after `cure_deadline` (at or before the deadline the attempt is `ERR_CURE_DEADLINE_NOT_PASSED`), and only when the authorizer's `X-User-ID` differs from `declared_by`, since the officer who declared the default may not also authorize its repossession (`ERR_SOD_VIOLATION`). Authorization moves the case to `REPOSSESSION_AUTHORIZED`.

Execution is the lessor's act. A `LessorAdmin` executing on a `REPOSSESSION_AUTHORIZED` case moves it to `REPOSSESSED` and fires a three-link cascade: the lease moves `DEFAULTED → TERMINATED`; because that lease is the one currently on the aircraft, the aircraft moves `ON_LEASE → REPOSSESSED`; and that seizure conditionally releases the aircraft's future — every transition slot of the aircraft in `TENTATIVE` or `CONFIRMED` moves to `RELEASED`, while `COMPLETED` or already-`RELEASED` slots are untouched — and any return case of the lease not yet `SETTLED` or `CANCELLED` is cascaded to `CANCELLED`.

Transition slots schedule the aircraft's next chapter. A `LessorAdmin` creates one on an aircraft with a `window_start` and a `window_end` — a closed interval, inclusive at both ends, with `window_end` on or after `window_start` — and an optional free-text `next_operator_ref`. The slot begins `TENTATIVE`. Two guards run at creation, in pipeline order: the buffer rule rejects the slot with `ERR_SLOT_WINDOW_CONFLICT` unless its window clears every other `TENTATIVE` or `CONFIRMED` window on the same aircraft by more than two whole days on one side or the other — adjacency within the two-day buffer counts as a conflict; and the default rule rejects it with `ERR_DEFAULT_CASE_OPEN` if the lease currently holding the aircraft (one in `ACTIVE`, `RETURN_INITIATED`, or `DEFAULTED`) has a default case in `DECLARED` or `REPOSSESSION_AUTHORIZED`.

From `TENTATIVE`, a `LessorAdmin` advances the slot to `CONFIRMED` once the aircraft is physically back — that is, when the aircraft's `status` is `IN_TRANSITION` or `REPOSSESSED` — or the settle cascade of §3.6 may confirm a covering slot automatically. Advancing a `CONFIRMED` slot to `COMPLETED` marks the transition done: the aircraft returns to `AVAILABLE` from either `IN_TRANSITION` or `REPOSSESSED`, and the aircraft's lease in `RETURNED` — at most one can exist — closes to `CLOSED`. A slot may instead be released from either `TENTATIVE` or `CONFIRMED` by advancing it to `RELEASED`, or by the repossession cascade above. `COMPLETED` and `RELEASED` are terminal, and every slot transition increments the slot's `version`, as each cascaded aircraft or lease transition increments that entity's `version` in turn.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or trigger a state transition return `200 OK`. The table below summarizes the HTTP contract only — request payloads, computed fields, and side effects are defined by the narratives in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/leasing/aircraft` | Register an aircraft (status starts `AVAILABLE`) | LessorAdmin |
| GET | `/leasing/aircraft/{id}` | Fetch one aircraft including computed totals and records score | LessorAdmin, CreditOfficer, LegalApprover, FinanceManager, LesseeRep, TechInspector |
| POST | `/leasing/aircraft/{id}/documents` | Submit a records document (`SUBMITTED`) | LessorAdmin |
| GET | `/leasing/aircraft/{id}/documents` | List an aircraft's documents | LessorAdmin, CreditOfficer, LegalApprover, FinanceManager, LesseeRep, TechInspector |
| POST | `/leasing/documents/{id}/review` | Verify or reject a records document | LessorAdmin |
| POST | `/leasing/aircraft/{id}/transition-slots` | Create a transition slot (`TENTATIVE`) with the two-day buffer check | LessorAdmin |
| GET | `/leasing/aircraft/{id}/transition-slots` | List an aircraft's transition slots | LessorAdmin, CreditOfficer, LegalApprover, FinanceManager, LesseeRep, TechInspector |
| POST | `/leasing/transition-slots/{id}/advance` | Advance a slot to `CONFIRMED`, `COMPLETED`, or `RELEASED` with cascades | LessorAdmin |
| POST | `/leasing/lessees` | Register a lessee (`ACTIVE`, credit tier default `B`) | LessorAdmin |
| GET | `/leasing/lessees` | Paginated lessee list, filterable by standing | LessorAdmin, CreditOfficer, LegalApprover, FinanceManager |
| GET | `/leasing/lessees/{id}` | Fetch one lessee | LessorAdmin, CreditOfficer, LegalApprover, FinanceManager, LesseeRep |
| POST | `/leasing/lessees/{id}/status` | Suspend or reinstate a lessee | CreditOfficer |
| GET | `/leasing/lessees/{id}/novation-requests` | List novation requests naming this lessee as proposed counterparty | LessorAdmin, CreditOfficer, LegalApprover |
| POST | `/leasing/inspectors` | Register an inspector | LessorAdmin |
| GET | `/leasing/inspectors/{id}` | Fetch one inspector | LessorAdmin, CreditOfficer, LegalApprover, FinanceManager, TechInspector |
| GET | `/leasing/inspectors/{id}/inspection-bookings` | List an inspector's bookings | LessorAdmin, CreditOfficer, LegalApprover, FinanceManager, TechInspector |
| POST | `/leasing/leases` | Create a lease in `DRAFT` (overlap checked at activation, not here) | LessorAdmin |
| GET | `/leasing/leases` | Paginated lease list with filters `aircraft_id`, `lessee_id`, `approved_sublessee_id`, `status` | LessorAdmin, CreditOfficer, LegalApprover, FinanceManager |
| GET | `/leasing/leases/{id}` | Fetch one lease including the reserve ledger fields | LessorAdmin, CreditOfficer, LegalApprover, FinanceManager, LesseeRep |
| PATCH | `/leasing/leases/{id}` | Amend lease terms (`DRAFT` or `ACTIVE`); OCC-guarded on lease version | LessorAdmin |
| POST | `/leasing/leases/{id}/activate` | Activate a `DRAFT` lease; records, overlap, availability, and standing gates | LessorAdmin |
| POST | `/leasing/leases/{id}/initiate-return` | Open a return case and generate its four-item checklist | LessorAdmin |
| POST | `/leasing/leases/{id}/abort-return` | Abort a return before inspection; cancels the open return case | LessorAdmin |
| GET | `/leasing/leases/{id}/monthly-charge` | Computed monthly charge for a `month`, using only that month's `ACCEPTED` report | LessorAdmin, FinanceManager, LesseeRep |
| POST | `/leasing/leases/{id}/utilization-reports` | Lessee submits a monthly utilization report (`SUBMITTED`) | LesseeRep |
| GET | `/leasing/leases/{id}/utilization-reports` | List a lease's utilization reports | LessorAdmin, CreditOfficer, LegalApprover, FinanceManager, LesseeRep |
| POST | `/leasing/utilization-reports/{id}/review` | Accept (posts accrual and aircraft totals) or dispute a report | LessorAdmin |
| POST | `/leasing/utilization-reports/{id}/revise` | Lessee revises a `DISPUTED` report back to `SUBMITTED` | LesseeRep |
| POST | `/leasing/utilization-reports/{id}/void` | Void an `ACCEPTED` report; exactly reverses accrual and aircraft totals | LessorAdmin |
| POST | `/leasing/leases/{id}/reserve-claims` | Lessee files a maintenance-reserve reimbursement claim (`SUBMITTED`) | LesseeRep |
| GET | `/leasing/leases/{id}/reserve-claims` | List a lease's reserve claims | LessorAdmin, CreditOfficer, LegalApprover, FinanceManager, LesseeRep |
| POST | `/leasing/reserve-claims/{id}/decide` | Approve (with an approved amount) or reject a `SUBMITTED` claim | LessorAdmin |
| POST | `/leasing/reserve-claims/{id}/pay` | Pay an `APPROVED` claim from the reserve (balance may equal the amount) | FinanceManager |
| POST | `/leasing/reserve-claims/{id}/reverse-payment` | Reverse a `PAID` claim, restoring the reserve balance | FinanceManager |
| GET | `/leasing/leases/{id}/return-cases` | List a lease's return cases | LessorAdmin, CreditOfficer, LegalApprover, FinanceManager, LesseeRep |
| GET | `/leasing/return-cases/{id}` | Fetch one return case including negotiation and settlement fields | LessorAdmin, CreditOfficer, LegalApprover, FinanceManager, LesseeRep, TechInspector |
| POST | `/leasing/return-cases/{id}/advance` | Advance the return workflow to `RECORDS_VERIFIED`, `INSPECTION`, or `NEGOTIATION` | LessorAdmin |
| POST | `/leasing/return-cases/{id}/inspection-bookings` | Book an inspector for a calendar date (capacity one per inspector per date) | LessorAdmin |
| GET | `/leasing/return-cases/{id}/inspection-bookings` | List a return case's bookings | LessorAdmin, CreditOfficer, LegalApprover, FinanceManager, LesseeRep, TechInspector |
| GET | `/leasing/return-cases/{id}/checklist-items` | List a return case's checklist items | LessorAdmin, CreditOfficer, LegalApprover, FinanceManager, LesseeRep, TechInspector |
| POST | `/leasing/checklist-items/{id}/inspect` | Booked inspector records `COMPLIANT` or `NON_COMPLIANT` (with estimate) | TechInspector |
| POST | `/leasing/checklist-items/{id}/waive` | Waive a `NON_COMPLIANT` item | LessorAdmin |
| POST | `/leasing/checklist-items/{id}/rectify` | Lessee marks a `NON_COMPLIANT` item rectified pending re-inspection | LesseeRep |
| POST | `/leasing/return-cases/{id}/proposals` | Negotiation round: alternating `LESSOR`/`LESSEE` lump-sum proposals | LessorAdmin, LesseeRep |
| POST | `/leasing/return-cases/{id}/agree` | Non-proposing side accepts the standing proposal; OCC-guarded | LessorAdmin, LesseeRep |
| POST | `/leasing/return-cases/{id}/request-reinspection` | Lessee loops the case back to `INSPECTION` (at most once) | LesseeRep |
| POST | `/leasing/return-cases/{id}/settle` | Execute settlement netting; cascades lease, aircraft, and slot states | FinanceManager |
| POST | `/leasing/leases/{id}/novation-requests` | Lessee requests a `NOVATION` or `SUBLEASE` to a proposed lessee | LesseeRep |
| GET | `/leasing/leases/{id}/novation-requests` | List a lease's novation requests | LessorAdmin, CreditOfficer, LegalApprover, LesseeRep |
| POST | `/leasing/novation-requests/{id}/review` | Stage-inferred review: `SUBMITTED` needs Credit, `CREDIT_APPROVED` needs Legal; SoD enforced | CreditOfficer, LegalApprover |
| POST | `/leasing/leases/{id}/default-cases` | Declare default; clock-derived deadline; lease moves to `DEFAULTED` | CreditOfficer |
| GET | `/leasing/leases/{id}/default-cases` | List a lease's default cases | LessorAdmin, CreditOfficer, LegalApprover, FinanceManager |
| POST | `/leasing/default-cases/{id}/cure` | Mark the default cured; lease reverts to `ACTIVE` | CreditOfficer |
| POST | `/leasing/default-cases/{id}/authorize-repossession` | Authorize repossession once the cure deadline has passed; SoD vs declarer | LegalApprover |
| POST | `/leasing/default-cases/{id}/execute-repossession` | Execute repossession; cascades to lease, aircraft, slots, and open return cases | LessorAdmin |
| POST | `/leasing/_clock/set_current_utc` | Set the logical clock (startup default `2026-08-01T00:00:00Z`; no wall-clock fallback) | LessorAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CLAIM_NOT_PAYABLE` | 409 |
| `ERR_RECORDS_INCOMPLETE` | 409 |
| `ERR_LEASE_PERIOD_OVERLAP` | 409 |
| `ERR_SLOT_WINDOW_CONFLICT` | 409 |
| `ERR_INSPECTOR_DOUBLE_BOOKED` | 409 |
| `ERR_DUPLICATE_REPORT_PERIOD` | 409 |
| `ERR_CHECKLIST_INCOMPLETE` | 409 |
| `ERR_PROPOSER_ALTERNATION` | 409 |
| `ERR_REINSPECTION_LIMIT` | 409 |
| `ERR_SOD_VIOLATION` | 409 |
| `ERR_CURE_DEADLINE_NOT_PASSED` | 409 |
| `ERR_BOOKING_REQUIRED` | 403 |
| `ERR_DEFAULT_CASE_OPEN` | 409 |
| `ERR_AIRCRAFT_NOT_AVAILABLE` | 409 |
| `ERR_LESSEE_NOT_ACTIVE` | 409 |
| `ERR_RESERVE_BALANCE_EXCEEDED` | 422 |
