# Tissue Bank Allograft API — Product Requirements Document

## 1. Introduction

Hospital tissue services operate under an unforgiving evidentiary burden: every allograft that enters the facility must be traceable from the moment it is received, through cold storage, to the moment it is implanted in a patient — and every deviation along the way must be documented well enough to survive a regulatory audit years later. This document specifies the Tissue Bank & Allograft Management API, the system of record for that chain of custody. It covers supplier qualification against accreditation and registration documents, receipt of consignments into monitored freezers, quarantine and release of individual tissue units, reservation and issue of units to operating rooms, implantation recording, recall execution, adverse-reaction investigation, and the long-term retention of disposition records.

Two design commitments shape everything that follows. First, the platform is conservative by default: a unit that has ever been inside a freezer during a temperature excursion, or that falls inside the scope of an active recall, is removed from circulation automatically and can only return to stock through an explicit, role-restricted decision. Second, the platform is ledger-minded about accountability: supplier quality is reduced to two continuously maintained scores that can suspend a supplier without human intervention, and every terminal movement of a unit generates a disposition record that cannot be destroyed for a fixed retention period. All business resources are mounted under `/tissue-bank`; a separate clock-driving capability at `/_clock/set_current_utc` exists so that time-dependent behavior (document expiry, tissue expiry, reservation expiry) can be exercised deterministically.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, structural contracts, and cross-cutting principles that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the capacity in which they act. The platform recognizes exactly five roles: `TissueBankCoordinator`, `QualityManager`, `ComplianceOfficer`, `ImplantingSurgeon`, and `SupplyChainAdmin`. A request missing either header, or presenting a role value outside these five, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Header values are stripped of surrounding whitespace before inspection, and an empty or whitespace-only value counts as missing. An authenticated operator whose role is not listed for the endpoint they call is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

For all five roles, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. When `X-User-Role` is `TissueBankCoordinator`, `QualityManager`, `ComplianceOfficer`, `ImplantingSurgeon`, or `SupplyChainAdmin`, the server never compares `X-User-ID` against any resource's `id`. It does, however, record the identifier on resources the operator touches — as `recorded_by_user_id` on temperature readings and disposition records, `verified_by_user_id` on verified supplier documents, `reported_by_user_id` on manually reported excursions, `resolved_by_user_id` on resolved excursions, `surgeon_id` on implant cases, `reporter_user_id` and `investigator_user_id` on adverse reaction cases, and `finalized_by_user_id` on finalized disposition records. Two kinds of rules compare against those recordings: implant-case ownership checks compare the case's `surgeon_id` to `X-User-ID`, and the segregation-of-duties rules described in §2.10 compare it to recorded verifier and reporter identifiers.

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
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object — with one exception: the 204 No Content disposition-record purge (§2.11) returns an empty response body with no envelope at all. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
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
- Requests to undeclared paths, and requests using an unsupported method on a declared path, are answered in this same error format with `error_id` `ERR_NOT_FOUND` (HTTP 404).

---

### 2.3. Pagination

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless a more specific ordering is stated for a particular list, every list endpoint returns resources sorted by `created_at` in ascending order.

Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope; `has_more` is true exactly when `offset` plus the number of items on the returned page is still below `total_count`. Optional filter parameters match by exact equality against the named field, apply before pagination (so `total_count` reflects the filtered set), and a filter value that matches nothing simply yields an empty page.

### 2.4. The Logical Clock and Time-Driven Sweeps

All time-dependent behavior in the platform is evaluated against a server-side logical clock, never against the host wall clock. Before any client sets it, the logical clock stands at exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time. A `SupplyChainAdmin` moves time forward through the clock-driving capability, supplying the target instant as `to_iso8601`; a `to_iso8601` earlier than the clock's current position is rejected with `ERR_INVALID_REQUEST`, while naming the current position exactly is accepted and simply re-runs the sweeps against it. The response echoes the new position as `current_utc` and reports how many sweeps fired as `documents_expired`, `units_expired`, `reservations_expired`, and `suppliers_auto_suspended` — `reservations_expired` counts every reservation moved to `EXPIRED` during the advance, including those dragged down by the unit sweep, and `suppliers_auto_suspended` counts each supplier that moved to `SUSPENDED` during the advance, at most once per supplier.

Advancing the clock synchronously executes three sweeps in a pinned order — documents first, then tissue units, then reservations. The document sweep expires any `VERIFIED` supplier document whose validity end is now strictly behind the clock (a document whose `valid_to` equals the clock remains `VERIFIED`), processing documents in ascending `valid_to` order with ties broken by ascending `created_at`. The unit sweep expires stored units whose `expiration_at` is now strictly behind the clock (equality leaves the unit usable), processing units in ascending `received_at` order with ties broken by ascending `created_at`. The reservation sweep expires `ACTIVE` reservations whose `hold_until` is now strictly behind the clock, processing reservations in ascending `hold_until` order with ties broken by ascending `created_at`. Because the document sweep can suspend suppliers and the unit sweep interacts with recalls, the ordering guarantee matters: document expiry cascades resolve before any unit-level expiry is considered, and unit-level effects resolve before reservation expiry. All datetime comparisons in the platform are made at second precision. Client-supplied datetimes are parsed as ISO 8601 with a trailing `Z` or a numeric offset, normalized to UTC, and truncated to second precision (a value without an offset is read as UTC); server-side instants derived from the logical clock — such as `received_at`, `opened_at`, `accepted_at`, `resolved_at`, `finalized_at`, `suspended_at`, `implanted_at`, `hold_until`, `current_utc`, and the stored document, case, and recall window bounds — are rendered at that same second precision.

### 2.5. Common Resource Properties

Every primary resource carries a standard set of system-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` is the ISO 8601 UTC timestamp of creation, rendered with three fractional digits. `updated_at` is the ISO 8601 UTC timestamp of the most recent modification, refreshed on every change to the resource. `version` is an integer that starts at 1 on creation and increments by one on every mutation of the resource.

Cascaded recomputations count as mutations: when an automatic sweep, a quarantine cascade, or a derived-field reconciliation changes a resource, that resource's `updated_at` is refreshed and its `version` is incremented. One resource type is deliberately lighter: a `TemperatureReading` is an immutable observation and carries only `id` and `created_at` — both `updated_at` and `version` are absent from it.

### 2.6. Nested Resource Retrieval

Endpoints whose paths contain more than one identifier validate those identifiers sequentially from left to right — the parent segment before the child segment — and the request is rejected with the 404 error corresponding to the first identifier that does not resolve. A verification call naming a document under a nonexistent supplier therefore fails with `ERR_SUPPLIER_NOT_FOUND` before the document identifier `docId` is ever examined; an unknown document under a real supplier fails with `ERR_DOCUMENT_NOT_FOUND`.

The full not-found vocabulary is: `ERR_SUPPLIER_NOT_FOUND` for suppliers, `ERR_DOCUMENT_NOT_FOUND` for supplier documents, `ERR_SHIPMENT_NOT_FOUND` for shipments, `ERR_UNIT_NOT_FOUND` for tissue units, `ERR_FREEZER_NOT_FOUND` for freezers, `ERR_EXCURSION_NOT_FOUND` for temperature excursions, `ERR_CASE_NOT_FOUND` for implant cases, `ERR_RESERVATION_NOT_FOUND` for reservations, `ERR_RECALL_NOT_FOUND` for recalls, `ERR_ADVERSE_REACTION_NOT_FOUND` for adverse reaction cases, `ERR_POLICY_NOT_FOUND` for par-level policies, and `ERR_DISPOSITION_NOT_FOUND` for disposition records. Existence checks on body-supplied references (such as the `supplier_id` or `freezer_id` named in a shipment manifest, or the `tissue_unit_id` named when reserving or reporting) follow the same vocabulary. Within the priority ladder of §2.8, existence of a body-supplied reference is evaluated directly after the request-shape rung — except on endpoints nested under a parent resource that carries ownership or state preconditions for the call (the implant-case endpoints), where those parent preconditions are evaluated first — and in all cases existence precedes the state-machine and compliance checks applied to the referenced entity itself.

### 2.7. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control; no other endpoint takes a version field.

Reconfiguring a freezer (`PUT /tissue-bank/freezers/{id}`) requires the request to carry `expected_freezer_version` holding the freezer `version` the client last observed. If the freezer's current `version` has moved past that value — whether because another writer reconfigured it or because a temperature-reading cascade bumped it — the update is rejected with `ERR_STALE_VERSION` (HTTP 412).

Creating a par-level policy (`POST /tissue-bank/par-level-policies`) for a tissue type that already has an `ACTIVE` policy supersedes that policy, and the request must carry `expected_current_policy_version` matching the currently `ACTIVE` policy's `version`. A missing `expected_current_policy_version` is treated as 0, which matches only when no `ACTIVE` policy exists for that tissue type. Any other mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

Updating a par-level policy's thresholds (`PUT /tissue-bank/par-level-policies/{id}`) requires `expected_par_level_policy_version` matching the policy's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). The OCC check on all three endpoints is evaluated before any business rule of the request.

### 2.8. Validation Order and the Priority Ladder

When a request violates several rules, the platform reports exactly one failure: the one from the earliest rung of a pinned priority ladder. The full order is:

1. **Header authentication** — presence of `X-User-ID` and `X-User-Role` and membership of the role in the five declared roles (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, 400).
2. **Role authorization** — the role is listed for the endpoint (`ERR_INSUFFICIENT_PERMISSIONS`, 403).
3. **Path existence** — identifiers resolve left to right (the 404 family of §2.6).
4. **Request shape** — required fields present, types correct, enum members valid, strings at or above their minimum lengths, arrays non-empty where required, and window or range sanity: `ERR_INVALID_REQUEST`, `ERR_INVALID_WINDOW`, and `ERR_INVALID_TEMP_RANGE` (all 400). This rung is deliberately pinned after headers and path existence but before OCC and before any state-machine precondition — a malformed body is reported only once the caller and the target are established. A malformed JSON body or a non-object JSON document fails with `ERR_INVALID_REQUEST`, an absent body is treated as an empty object, and unrecognized body fields (including system-managed keys smuggled into a request) are ignored.
5. **Optimistic concurrency** — the `expected_*_version` checks of §2.7 (`ERR_STALE_VERSION`, 412), evaluated before any business rule.
6. **State-machine preconditions** — the target must be in a state from which the requested transition exists (409), drawing from `ERR_SUPPLIER_INVALID_STATE`, `ERR_DOCUMENT_INVALID_STATE`, `ERR_SHIPMENT_NOT_RECEIVED`, `ERR_SHIPMENT_NOT_ACCEPTED`, `ERR_UNIT_NOT_QUARANTINED`, `ERR_UNIT_NOT_HOLDABLE`, `ERR_UNIT_NOT_ISSUABLE_STATE`, `ERR_UNIT_NOT_ISSUED`, `ERR_UNIT_NOT_RESERVABLE`, `ERR_UNIT_NOT_DISCARDABLE`, `ERR_RESERVATION_NOT_ACTIVE`, `ERR_CASE_INVALID_STATE`, `ERR_EXCURSION_INVALID_STATE`, `ERR_RECALL_INVALID_STATE`, `ERR_ADVERSE_INVALID_STATE`, and `ERR_DISPOSITION_INVALID_STATE`.
7. **Compliance gates** — supplier qualification and document verification, unit expiry at movement time, active-recall matches, freezer excursion lockout, and high-severity destroy mandates: `ERR_SUPPLIER_NOT_QUALIFIED`, `ERR_REQUIRED_DOCUMENTS_NOT_VERIFIED`, `ERR_UNIT_EXPIRED`, `ERR_UNIT_UNDER_ACTIVE_RECALL`, `ERR_FREEZER_IN_EXCURSION`, and `ERR_SEVERITY_REQUIRES_DESTROY` (all 403).
8. **Temporal gates** — the implant window, reservation-versus-expiry ordering, and disposition retention: `ERR_IMPLANT_WINDOW_CLOSED`, `ERR_UNIT_EXPIRES_BEFORE_CASE`, and `ERR_RETENTION_PERIOD_ACTIVE` (all 409).
9. **Structural constraints** — operating-room overlap, document validity overlap, freezer capacity including the quarantine reserve, segregation of duties, and uniqueness of supplier license, freezer name, and manifest serial: `ERR_OR_ROOM_DOUBLE_BOOKED`, `ERR_DOC_VALIDITY_OVERLAP`, `ERR_FREEZER_CAPACITY_EXCEEDED`, `ERR_CAPACITY_BELOW_OCCUPIED`, `ERR_SEGREGATION_OF_DUTIES`, and `ERR_DUPLICATE_VALUE` (all 409).
10. **Referential integrity** — cross-entity mismatches: `ERR_RESERVATION_UNIT_MISMATCH`, `ERR_UNIT_ISSUED_TO_ANOTHER_CASE`, and `ERR_UNIT_NOT_IMPLANTED_ON_CASE` (all 422).
11. **Fiscal caps** — the inventory value ceiling at shipment acceptance (`ERR_INVENTORY_VALUE_CAP_EXCEEDED`, 402), evaluated last.

### 2.9. Precision, Rounding, and Monetary Representation

Monetary amounts are carried as integer cents — acquisition cost `unit_cost_cents`, declared shipment value `total_declared_value_cents`, and policy ceiling `max_inventory_value_cents` are all integer cent figures, and FIFO valuations are exact integer-cent sums. Where a division is unavoidable (the weighted-average valuation of §3.9), the mean is kept as an exact, unrounded quotient and rounding to 2 decimal places with the round-half-up rule is applied per lot line, never to the intermediate average.

Freezer `utilization_pct` is rendered rounded half-up to 2 decimal places, while the 80% quarantine-reserve trigger of §3.3 is evaluated on the exact, unrounded ratio of `occupied_count` to `nominal_capacity`, not on the rendered figure. Supplier qualification scores and excursion severity scores are integer points; qualification scores are floored at 0, and excursion duration is truncated to whole hours before scoring.

### 2.10. Segregation of Duties

Three decision pairs are segregated: the same operator may not perform both halves. First, the `ComplianceOfficer` who approves a supplier must not be the operator recorded as `verified_by_user_id` on the most recently verified required-type document of that supplier — verification recency is ranked across every required-type document that has ever been verified, including any that have since expired. Second, the `QualityManager` who resolves a manually reported excursion must not be the operator recorded as `reported_by_user_id` on it (excursions opened automatically by an out-of-range reading carry no reporter, so this restriction does not apply to them). Third, the `ComplianceOfficer` who resolves an adverse reaction case must not be the surgeon recorded as `reporter_user_id` on it. Any violation of these three pairings is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409).

### 2.11. Disposition Records and Retention

Every terminal movement of a tissue unit — implantation, destruction, return to supplier, and expiry — generates a `DispositionRecord` in `DRAFT` status, stamped with the `tissue_unit_id`, the `disposition_type` (one of `IMPLANTED`, `DESTROYED`, `RETURNED_TO_SUPPLIER`, or `EXPIRED`), a free-text `reason` captured from the triggering action, and the `recorded_by_user_id` of the actor whose action created it. A draft is evidentiary scaffolding, not a finished record.

A `ComplianceOfficer` finalizes a draft, which moves the record to `FINALIZED`, stamps `finalized_at` with the logical clock, and records the officer as `finalized_by_user_id`. Finalizing a record that is not in `DRAFT` is rejected with `ERR_DISPOSITION_INVALID_STATE`. Once finalized, a record is immutable, and its retention clock starts: deletion is permitted only when the logical clock has reached at least `finalized_at` plus 3650 days — a ten-year retention floor. Purging earlier is rejected with `ERR_RETENTION_PERIOD_ACTIVE` (HTTP 409), and attempting to delete a record still in `DRAFT` is rejected with `ERR_DISPOSITION_INVALID_STATE`. A successful purge returns 204 with no data.

## 3. Business Logic & Workflows

### 3.1. Supplier Registration, Regulatory Documents, and Qualification

A `QualityManager` onboards a new tissue source by registering a supplier with its `legal_name` and `license_number`. The license number is unique across suppliers; a duplicate submission is rejected with `ERR_DUPLICATE_VALUE`. New suppliers begin in `PENDING_QUALIFICATION` with both qualification scores at 100 and `suspended_at` unset — it remains null until the supplier's first suspension. The supplier list is sorted by `created_at` ascending with ties broken by `license_number` ascending, and can be narrowed with the optional `status` filter.

Qualification rests on documentary evidence. The quality team submits each regulatory document with a `doc_type` — one of `AATB_ACCREDITATION`, `FDA_REGISTRATION`, `STATE_LICENSE`, or `ISO_CERTIFICATE` — together with its external `document_ref` and a validity window from `valid_from` to `valid_to`. The window is a closed interval, inclusive at both ends, and `valid_to` must not fall before `valid_from` (reversed windows are rejected with `ERR_INVALID_WINDOW`). One supplier may not hold overlapping validity windows for the same `doc_type` among its `SUBMITTED` and `VERIFIED` documents: because the interval is closed, windows that merely touch at an endpoint still conflict, and the submission is rejected with `ERR_DOC_VALIDITY_OVERLAP`. New documents enter as `SUBMITTED`; the document list is ordered by `created_at` ascending with ties broken by `document_ref` ascending, and supports the optional `doc_type` filter.

A `QualityManager` then adjudicates each submission. Verification moves a document from `SUBMITTED` to `VERIFIED` and stamps the acting operator into `verified_by_user_id`; rejection moves it to `REJECTED`. Both actions are defined only from `SUBMITTED` — acting on a document in any other status fails with `ERR_DOCUMENT_INVALID_STATE`.

Approval is the compliance function's decision. A `ComplianceOfficer` qualifies a supplier whose `status` is `PENDING_QUALIFICATION` or `SUSPENDED`; any other starting state is rejected with `ERR_SUPPLIER_INVALID_STATE`. Approval requires documentary coverage: at least one `VERIFIED` document of type `AATB_ACCREDITATION` whose `valid_to` is on or after the current clock, and at least one `VERIFIED` document of type `FDA_REGISTRATION` meeting the same condition — a lapse in either is rejected with `ERR_REQUIRED_DOCUMENTS_NOT_VERIFIED`. The segregation-of-duties rule of §2.10 also applies, so the approver cannot be the operator who verified the most recently verified required-type document. Successful approval sets `status` to `QUALIFIED` and increments the supplier's `version` by one.

Once qualified, a supplier can leave good standing in three ways. A `ComplianceOfficer` may suspend a `QUALIFIED` supplier outright; suspension stamps `suspended_at` with the clock. The platform also suspends automatically when required-document coverage lapses — the moment the clock sweep expires the last `VERIFIED` `AATB_ACCREDITATION` or `FDA_REGISTRATION` document with no replacement of the same type valid on or after the clock — and when the provisional qualification score falls below the suspension threshold, both detailed in §3.8. From `SUSPENDED`, reinstatement by a `ComplianceOfficer` re-applies the same documentary coverage check as approval (`ERR_REQUIRED_DOCUMENTS_NOT_VERIFIED` on lapse) and additionally demands a `qualification_score_provisional` of at least 60; a weaker score is rejected with `ERR_SUPPLIER_SCORE_BELOW_THRESHOLD`. Finally, disqualification is permanent: a `ComplianceOfficer` may move a supplier from `PENDING_QUALIFICATION` or `SUSPENDED` to the terminal `DISQUALIFIED` state, and any mutation of a `DISQUALIFIED` supplier's own state — including a fresh approval — as well as any new document submission under it is rejected with `ERR_SUPPLIER_INVALID_STATE`; verifying or rejecting an already-submitted document of a disqualified supplier remains lawful.

### 3.2. Receiving Shipments and Minting Tissue Units

Inbound tissue arrives as a shipment received by a `TissueBankCoordinator`, who names the originating `supplier_id`, the receiving `freezer_id`, and a manifest `items` array. The manifest must contain at least one line, and each line declares a `tissue_type` (`BONE`, `SOFT_TISSUE`, `CARDIOVASCULAR`, `SKIN`, or `CORNEA`), a manufacturer `lot_number`, a `serial_number` unique within the shipment (duplicates across two lines of the same manifest are rejected with `ERR_DUPLICATE_VALUE`), a non-negative acquisition `unit_cost_cents`, an `expiration_at` instant, and a `criticality_tier` of `STANDARD`, `SENSITIVE`, or `CRITICAL`.

Receipt is gated twice before any unit exists. The supplier must be `QUALIFIED` at receipt time — consignments from suspended, pending, or disqualified sources are refused with `ERR_SUPPLIER_NOT_QUALIFIED`. The destination freezer must be able to admit the full manifest under its `effective_capacity`: if the manifest's line count would push occupancy beyond that figure, receipt is refused with `ERR_FREEZER_CAPACITY_EXCEEDED` (§3.3 defines the capacity arithmetic). Only then does the platform accept the manifest: the shipment is recorded in `RECEIVED` status with `received_at` set to the clock, `total_declared_value_cents` computed as the sum of every line's `unit_cost_cents`, and `unit_count` equal to the number of manifest lines. One `TissueUnit` is minted per line, each starting in `QUARANTINED` with `hold_reason` `NONE`, carrying its line's attributes plus its `shipment_id`, the denormalized `supplier_id`, the storage `freezer_id`, and a `received_at` copied from the shipment's receipt instant.

A received shipment then faces a binary inspection outcome. Rejection by a `TissueBankCoordinator` requires a `rejection_reason` of at least ten characters (anything shorter fails with `ERR_INVALID_REQUEST`) and moves the shipment to `REJECTED`; every minted unit is moved to `RETURNED_TO_SUPPLIER` whatever its current status (a unit the clock has already swept to `EXPIRED` included) with `hold_reason` cleared to `NONE`, one `DRAFT` disposition record of type `RETURNED_TO_SUPPLIER` is created per unit under the coordinator's `recorded_by_user_id`, and the freezer's `occupied_count` drops accordingly for each unit that had still been stored. Both acceptance and rejection are defined only from `RECEIVED`; acting on a decided shipment fails with `ERR_SHIPMENT_NOT_RECEIVED`.

Acceptance re-verifies the compliance envelope at decision time rather than trusting receipt-time checks: the supplier must still be `QUALIFIED` (`ERR_SUPPLIER_NOT_QUALIFIED`) and must still hold `VERIFIED` `AATB_ACCREDITATION` and `FDA_REGISTRATION` documents valid on or after the clock (`ERR_REQUIRED_DOCUMENTS_NOT_VERIFIED`). On top of compliance sits the fiscal cap of §3.9: for every tissue type in the shipment that has an `ACTIVE` par-level policy, acceptance is refused with `ERR_INVENTORY_VALUE_CAP_EXCEEDED` (HTTP 402) if the projected weighted-average valuation including the incoming units would exceed the policy's `max_inventory_value_cents`. Successful acceptance moves the shipment to `ACCEPTED`, stamps `accepted_at` with the clock, and admits the shipment's units into the valuation population.

### 3.3. Cold Storage: Freezers, Temperature Readings, and Excursions

A `SupplyChainAdmin` registers each storage unit with a display `name` (unique across freezers, duplicates failing with `ERR_DUPLICATE_VALUE`), an in-range band from `min_celsius` to `max_celsius` inclusive at both bounds, and a physical `nominal_capacity` of at least one slot. A band whose lower bound is not strictly below its upper bound is rejected with `ERR_INVALID_TEMP_RANGE`; a capacity below one fails with `ERR_INVALID_REQUEST`. New freezers begin `OPERATIONAL`.

Capacity bookkeeping is derived, and the derivation order is pinned because the terms depend on one another. First, `occupied_count` counts the units stored in the freezer — those in `QUARANTINED`, `AVAILABLE`, or `RESERVED`. Second, `utilization_pct` is `occupied_count` divided by `nominal_capacity`, multiplied by 100, at two decimal places. Third, `quarantine_reserve_slots` is 2 when `utilization_pct` reaches at least 80.0, and 0 otherwise. Fourth, `effective_capacity` is `nominal_capacity` minus `quarantine_reserve_slots`. Admission follows: storing N additional units requires `occupied_count` plus N to stay at or below `effective_capacity` — equality is admitted — otherwise the operation fails with `ERR_FREEZER_CAPACITY_EXCEEDED`. The evaluation is performed strictly in this numbered order and never iterated to a fixed point. Reconfiguring a freezer by a `SupplyChainAdmin` may change `min_celsius`, `max_celsius`, or `nominal_capacity` (each optional in the request, but `expected_freezer_version` is mandatory per §2.7); the new `nominal_capacity` must leave `occupied_count` no greater than the new capacity minus the reserve computed from the new utilization, and a configuration that strands existing stock is rejected with `ERR_CAPACITY_BELOW_OCCUPIED`. A successful reconfiguration increments the freezer's `version` by one.

Surveillance runs through temperature readings posted by a `TissueBankCoordinator`, each carrying the observed `temp_celsius`. The platform computes `in_range` once, at record time, by comparing the observation against the freezer's `min_celsius` and `max_celsius` as they stand at that moment, and freezes that verdict on the reading — the reading carries no separate bounds fields, and later reconfiguration of the freezer's range never rewrites it — and stamps `recorded_by_user_id` with the acting operator. An in-range reading is a plain observation with `excursion_id` null. An out-of-range reading — strictly above `max_celsius` or strictly below `min_celsius` — opens a `TemperatureExcursion` of `origin` `AUTO_READING` in `OPEN` status while the freezer is `OPERATIONAL`, or extends the freezer's unresolved excursion while one is already active; either way the reading's `excursion_id` links it to that excursion, and the excursion's `last_reading_at` advances to the reading's clock time. An excursion can also be reported manually by a `TissueBankCoordinator` with a free-text `reason`; manual reports carry `origin` `MANUAL_REPORT` and stamp `reported_by_user_id`, start with `max_deviation_celsius` at 0, and are refused with `ERR_EXCURSION_INVALID_STATE` while the freezer is already `EXCURSION_ACTIVE`.

Opening an excursion flips the freezer from `OPERATIONAL` to `EXCURSION_ACTIVE`, records the new excursion as the freezer's `current_excursion_id`, increments the freezer's `version` by one, and fires the quarantine cascade: every unit stored there in `AVAILABLE` moves to `QUARANTINED` with `hold_reason` `EXCURSION`, every `RESERVED` unit moves to `QUARANTINED` with `hold_reason` `EXCURSION` while its `ACTIVE` reservation is released with `release_reason` `EXCURSION`, and par-level availability is recomputed for each affected tissue type. Units already `QUARANTINED` stay put, and their `hold_reason` is overwritten to `EXCURSION` only when it was previously `NONE` — a unit already held for a recall keeps its recall attribution. The excursion's own bookkeeping tracks `opened_at`; `last_reading_at`, initialized to the opening instant (so a manual report with no linked readings shows its `opened_at` time) and advancing to each subsequent linked reading's clock time; the `max_deviation_celsius` observed across its linked readings — for each reading the largest of zero, the amount by which the temperature exceeded `max_celsius`, and the amount by which it fell below `min_celsius`, taking the maximum over all linked readings — and `affected_unit_count`, the number of units in the freezer currently held with `hold_reason` `EXCURSION`. The freezer list accepts optional `status` and `current_excursion_id` filters, the latter locating the freezer holding a given excursion, and both the freezer's reading log and its excursion history are listed in `created_at` ascending order.

Investigation and resolution belong to the `QualityManager`. Opening an investigation moves the excursion from `OPEN` to `UNDER_INVESTIGATION`; both investigation and resolution are rejected with `ERR_EXCURSION_INVALID_STATE` from any other state. Resolution requires a `disposition` of `RELEASE` or `DESTROY` and `resolution_notes` of at least ten characters (shorter notes fail with `ERR_INVALID_REQUEST`), honors the segregation rule of §2.10 against `reported_by_user_id` for manually reported excursions, and is gated by severity: an excursion whose `severity_class` is `HIGH` may not be released — such a resolution is rejected with `ERR_SEVERITY_REQUIRES_DESTROY`, leaving destruction as the only lawful outcome.

The severity model itself is computed on read and at resolution time, in integer points from 0 to 100. Deviation contributes the smaller of 40 points and the `max_deviation_celsius` rounded up to the next whole degree, multiplied by 8 points per degree. Duration contributes 6 points per full hour between `opened_at` and the resolution time — or the current clock while unresolved — with partial hours discarded, capped at 30 points. Affected stock contributes 2 points per unit held for this excursion, capped at 20 points. Criticality contributes 10 points when the highest `criticality_tier` among affected units is `CRITICAL`, 5 when it is `SENSITIVE`, and 0 when it is `STANDARD` — and an excursion holding no units is scored as `STANDARD`. The four components sum to `severity_score`; `severity_class` is `LOW` below 25 points, `MEDIUM` from 25 up to and including 59, and `HIGH` at 60 or above.

Resolution moves the excursion into the terminal state matching its disposition — `RESOLVED_RELEASE` for a release, `RESOLVED_DESTROY` for a destruction — and cascades back into stock. A `RELEASE` resolution moves every unit held with `hold_reason` `EXCURSION` in that freezer back to `AVAILABLE` with `hold_reason` cleared to `NONE`. A `DESTROY` resolution moves those same units to `DISCARDED`, clears their `hold_reason`, and creates one `DRAFT` disposition record of type `DESTROYED` per unit. Either resolution stamps `resolved_by_user_id` and `resolved_at`, returns the freezer to `OPERATIONAL` with `current_excursion_id` cleared to null, and — for destroy outcomes — recomputes par-level availability for each affected tissue type.

### 3.4. The Tissue Unit Lifecycle

Units are born in quarantine and earn their way to the shelf. A `QualityManager` releases a `QUARANTINED` unit to `AVAILABLE` only when the whole compliance envelope holds: the unit must actually be `QUARANTINED` (`ERR_UNIT_NOT_QUARANTINED`), its shipment must be `ACCEPTED` (`ERR_SHIPMENT_NOT_ACCEPTED`), its supplier must be `QUALIFIED` (`ERR_SUPPLIER_NOT_QUALIFIED`), its freezer must be `OPERATIONAL` rather than `EXCURSION_ACTIVE` (`ERR_FREEZER_IN_EXCURSION`), and no `ACTIVE` recall may match the unit (`ERR_UNIT_UNDER_ACTIVE_RECALL` — matching means the recall names the unit's supplier, the unit's `lot_number` appears among the recall's `lot_numbers`, and the unit's `received_at` falls inside the recall's received window inclusive at both ends). Release clears `hold_reason` to `NONE`.

Holds flow in the other direction. A `QualityManager` can manually quarantine an `AVAILABLE` unit — attempting it on any other status fails with `ERR_UNIT_NOT_HOLDABLE` — which records `hold_reason` `MANUAL`. The platform itself imposes holds for excursions (§3.3) and recalls (§3.6), attributing `hold_reason` `EXCURSION` or `RECALL` respectively; attribution is written onto already-quarantined units only when the previous reason was `NONE`. The `hold_reason` vocabulary — `NONE`, `EXCURSION`, `RECALL`, `MANUAL` — is meaningful only while a unit is `QUARANTINED`.

Issuance moves a unit to the operating room and is performed by a `TissueBankCoordinator` in one of two shapes. Direct issue requires the unit to be `AVAILABLE` (otherwise `ERR_UNIT_NOT_ISSUABLE_STATE`); issue against a reservation carries an optional `reservation_id` in the request and requires the unit to be `RESERVED`, the named reservation to be `ACTIVE` (`ERR_RESERVATION_NOT_ACTIVE`), and the reservation's `tissue_unit_id` to match the unit being issued (`ERR_RESERVATION_UNIT_MISMATCH`). Both shapes then apply the movement gates: the clock must be on or before the unit's `expiration_at` — a lapsed unit fails with `ERR_UNIT_EXPIRED` — the freezer must be `OPERATIONAL` (`ERR_FREEZER_IN_EXCURSION`), no `ACTIVE` recall may match (`ERR_UNIT_UNDER_ACTIVE_RECALL`), and the supplier must be `QUALIFIED` (`ERR_SUPPLIER_NOT_QUALIFIED`). A successful issue moves the unit to `ISSUED`, fulfills the reservation when one was used (its status becomes `FULFILLED`), and decrements the freezer's `occupied_count`.

An unopened issued unit can come back. Return-to-stock by a `TissueBankCoordinator` requires the unit to be `ISSUED` (`ERR_UNIT_NOT_ISSUED`), the clock still on or before `expiration_at` (`ERR_UNIT_EXPIRED`), and no `ACTIVE` recall match (`ERR_UNIT_UNDER_ACTIVE_RECALL`) — note that a unit whose `recall_flag` was set by a recall sweep necessarily matches an active recall while that recall runs, so flagged units cannot return to stock. There must also be a free slot: `occupied_count` plus one must stay at or below the freezer's `effective_capacity`, otherwise `ERR_FREEZER_CAPACITY_EXCEEDED`. A successful return moves the unit back to `AVAILABLE`, clears `recall_flag` to false, and increments `occupied_count`. More generally, `recall_flag` is set when an `ACTIVE` recall matches an `ISSUED` unit and is cleared whenever the unit leaves `ISSUED`.

Destruction and supplier return are quality decisions over quarantined or expired stock. Discarding takes a free-text `reason`, requires the unit to be `QUARANTINED` or `EXPIRED` (`ERR_UNIT_NOT_DISCARDABLE`), moves it to `DISCARDED`, clears `hold_reason` to `NONE` and `recall_flag` to false, creates a `DRAFT` disposition record of type `DESTROYED`, and decrements the freezer's `occupied_count` when the unit was still stored. Returning a unit to its supplier likewise takes a `reason`, requires `QUARANTINED` (`ERR_UNIT_NOT_QUARANTINED`), moves the unit to `RETURNED_TO_SUPPLIER` with `hold_reason` cleared, creates a `DRAFT` disposition record of type `RETURNED_TO_SUPPLIER`, and decrements `occupied_count`.

Expiry is the clock's business, not an operator's. A unit is usable while the clock is on or before its `expiration_at`; once the clock is strictly past it, the expiration sweep moves units in `QUARANTINED`, `AVAILABLE`, or `RESERVED` to the terminal `EXPIRED` state with `hold_reason` cleared to `NONE`, creates a `DRAFT` disposition record of type `EXPIRED` per unit, and decrements `occupied_count` for stored units — an expired unit can still be formally discarded later. A reserved unit that expires takes its `ACTIVE` reservation down with it: the reservation becomes `EXPIRED` with `release_reason` `CLOCK_EXPIRED`. Units in `ISSUED` are deliberately not swept — clinical custody overrides expiry — though issue and return-to-stock continue to enforce the expiry gate. The full unit roster is sorted by `serial_number` ascending with ties broken by creation order, and supports the optional filters `supplier_id`, `freezer_id`, `shipment_id`, `status`, `tissue_type`, `lot_number`, and `implanted_case_id`; the per-freezer unit listing follows the same serial ordering. Each unit also exposes its reservation history, its disposition records, and its adverse-reaction history, all listed in `created_at` ascending order.

### 3.5. Implant Cases and Reservations

An `ImplantingSurgeon` schedules a case with a de-identified `patient_ref`, an `or_room_id` identifying the operating room, and a window from `scheduled_start` to `scheduled_end`; the window must be strictly ordered, with an end at or before the start rejected as `ERR_INVALID_WINDOW`. The creating operator's `X-User-ID` is stamped as `surgeon_id`, and it is the ownership anchor for everything the surgeon later does on the case. Double-booking is forbidden across the room's active calendar: a new case whose half-open window — start inclusive, end exclusive — intersects another `SCHEDULED` case in the same `or_room_id` is rejected with `ERR_OR_ROOM_DOUBLE_BOOKED`, while back-to-back cases whose boundary instants coincide are lawful because the touching endpoint lies outside the half-open interval. New cases begin `SCHEDULED` with `implanted_unit_count` at zero.

Against a scheduled case, a `TissueBankCoordinator` reserves stock by naming a `tissue_unit_id`. A reservation attempt against a case no longer `SCHEDULED` fails with `ERR_CASE_INVALID_STATE`. The unit must be `AVAILABLE` (`ERR_UNIT_NOT_RESERVABLE`), and it must outlive the surgery: its `expiration_at` must fall strictly after the case's `scheduled_end`, otherwise the reservation is refused with `ERR_UNIT_EXPIRES_BEFORE_CASE`. A successful reservation creates an `ACTIVE` reservation bound to the case through its `implant_case_id`, with `hold_until` computed as the case's `scheduled_end` plus two hours, and moves the unit to `RESERVED`.

Reservations unwind through several doors, each leaving a distinct audit trail in `release_reason`. A `TissueBankCoordinator` may release an `ACTIVE` reservation manually (`ERR_RESERVATION_NOT_ACTIVE` on anything else), recording `MANUAL` and returning the unit to `AVAILABLE`. Excursion and recall sweeps release reservations with `EXCURSION` or `RECALL`, driving the unit into `QUARANTINED` rather than back to stock. Cancelling or completing the parent case releases each of its remaining `ACTIVE` reservations with `CASE_CANCELLED` or `CASE_COMPLETED`, returning those units to `AVAILABLE`. The reservation sweep expires an `ACTIVE` reservation once the clock is strictly past `hold_until`, recording `CLOCK_EXPIRED` and returning a still-`RESERVED` unit to `AVAILABLE`; the mirror-image path is the unit-expiry cascade of §3.4, where the unit reaches `EXPIRED` first and drags the reservation to `EXPIRED` with the same `CLOCK_EXPIRED` reason. Issue against a reservation fulfills it (`FULFILLED`). The reason vocabulary is therefore `NONE`, `MANUAL`, `EXCURSION`, `RECALL`, `CASE_CANCELLED`, `CASE_COMPLETED`, and `CLOCK_EXPIRED`, and a reservation's terminal states are `RELEASED`, `FULFILLED`, and `EXPIRED`.

Recording the implantation itself is the surgeon's act, guarded on four axes. Ownership: the case's `surgeon_id` must equal the caller's `X-User-ID`, otherwise `ERR_CASE_OWNERSHIP_VIOLATION` (HTTP 403). State: the case must still be `SCHEDULED`, otherwise `ERR_CASE_INVALID_STATE`. Timing: the clock must sit inside the implant window — no earlier than one hour before `scheduled_start` and no later than twenty-four hours after `scheduled_end`, inclusive at both ends — otherwise `ERR_IMPLANT_WINDOW_CLOSED`. Stock: the named `tissue_unit_id` must be `ISSUED` (`ERR_UNIT_NOT_ISSUED`), and if that unit reached `ISSUED` through a reservation, the reservation's case must be this case — implanting another case's reserved unit fails with `ERR_UNIT_ISSUED_TO_ANOTHER_CASE` (HTTP 422). Success moves the unit to `IMPLANTED`, stamps `implanted_case_id` and `implanted_at`, clears `recall_flag`, increments the case's `implanted_unit_count` by one, and creates a `DRAFT` disposition record of type `IMPLANTED` under the surgeon's `recorded_by_user_id`; the response returns the implanted unit object.

Closing the case is symmetric. Both cancellation and completion require the same ownership check (`ERR_CASE_OWNERSHIP_VIOLATION`) and a `SCHEDULED` case (`ERR_CASE_INVALID_STATE`); cancellation moves the case to `CANCELLED`, completion to `COMPLETED`, and both release remaining reservations as described above. The case's reservation list and its adverse-reaction list are each enumerated in `created_at` ascending order.

### 3.6. Recalls

A `QualityManager` drafts a recall by naming the responsible `supplier_id` (which need only exist — a recall may be drafted against a supplier in any status), a non-empty `lot_numbers` list, a received window from `received_window_start` to `received_window_end` — a closed interval inclusive at both ends, with an end before the start rejected as `ERR_INVALID_WINDOW` — and a free-text `reason`. The draft sits in `DRAFT` with `closure_reason` `NONE` and `affected_unit_count` at zero, gathering no dust and touching no stock.

Activation is where the recall bites, and it is defined only from `DRAFT` (`ERR_RECALL_INVALID_STATE` otherwise). The platform sweeps every unit matching the scope — supplier matches, `lot_number` appears among `lot_numbers`, `received_at` inside the received window inclusive — in a deterministic order: `received_at` ascending, ties broken by `created_at` ascending. Each matched unit is handled by status: an `AVAILABLE` unit moves to `QUARANTINED` with `hold_reason` `RECALL`; a `RESERVED` unit moves to `QUARANTINED` with `hold_reason` `RECALL` while its `ACTIVE` reservation is released with `release_reason` `RECALL`; a unit already `QUARANTINED` with `hold_reason` `NONE` has its reason rewritten to `RECALL`; and an `ISSUED` unit — already in clinical custody — is not moved but has its `recall_flag` set to true, which blocks its return to stock until the flag clears on leaving `ISSUED`. The recall records how many units matched in any status as `affected_unit_count` and stamps `activated_at` with the clock. If the sweep matches nothing, the recall closes itself immediately: it transitions from `DRAFT` straight to `CLOSED` with `closure_reason` `NO_MATCH`, and `activated_at` remains stamped with the activation instant. Activation also feeds the supplier score model — the recall joins the provisional score's active-recall term, and if that recomputation drops a `QUALIFIED` supplier below the suspension threshold, the supplier is automatically suspended (§3.8).

Closing an active recall is a manual attestation that the sweep's work is done. It is defined only from `ACTIVE` (`ERR_RECALL_INVALID_STATE`), and it is refused with `ERR_RECALL_UNRESOLVED_UNITS` while any unit matching the recall's scope still sits in `QUARANTINED` with `hold_reason` `RECALL` — such units must first be released, returned to the supplier, discarded, or swept to expiry. A clean close moves the recall to `CLOSED` with `closure_reason` `RESOLVED` and recomputes the supplier's scores, the recall leaving the provisional model's active-recall term. A supplier's recall history is listed under the supplier in `created_at` ascending order.

### 3.7. Adverse Reaction Cases

When a patient reacts to an implanted allograft, the `ImplantingSurgeon` who owns the case reports it — acting on another surgeon's case fails ownership with `ERR_CASE_OWNERSHIP_VIOLATION`. Reporting is not gated on the case's `status`: a reaction may be reported while the case is `SCHEDULED` or after it has closed. The report names the implicated `tissue_unit_id`, a `reaction_type` of `INFECTION`, `REJECTION`, or `OTHER`, a `severity` of `MINOR`, `MAJOR`, or `CRITICAL`, and a free-text `description` of at least ten characters. The named unit must actually be `IMPLANTED` on this case; a unit with any other placement fails with `ERR_UNIT_NOT_IMPLANTED_ON_CASE` (HTTP 422). The case opens in `REPORTED` with the surgeon stamped as `reporter_user_id` and `reopened_count` at zero, and the supplier's provisional score immediately absorbs the open-case term (§3.8).

Investigation and adjudication belong to the `ComplianceOfficer`. Opening an investigation is defined from `REPORTED` and from `REOPENED` alike — any other state fails with `ERR_ADVERSE_INVALID_STATE` — and moves the case to `UNDER_INVESTIGATION`. Resolution supplies an `outcome` of `CONFIRMED` or `UNCONFIRMED` plus `outcome_notes` of at least ten characters (`ERR_INVALID_REQUEST` on shorter notes), is permitted only from `UNDER_INVESTIGATION` (`ERR_ADVERSE_INVALID_STATE`), and observes the segregation rule of §2.10: the resolving officer must not be the `reporter_user_id` (`ERR_SEGREGATION_OF_DUTIES`). A confirmed outcome moves the case to `CLOSED_CONFIRMED`, stamps `investigator_user_id`, and lands a confirmed finding on the supplier — both qualification scores drop by 20 points, and if the provisional score falls below the suspension threshold while the supplier is `QUALIFIED`, automatic suspension follows. An unconfirmed outcome moves the case to `CLOSED_UNCONFIRMED` and recomputes the scores as the case leaves the provisional model's open-case term.

Closure is not necessarily final. Either closed state can be reopened by a `ComplianceOfficer` supplying a `reopen_reason` of at least ten characters, moving the case to `REOPENED` and incrementing `reopened_count` by one. Reopening a case that was `CLOSED_CONFIRMED` reverses its confirmed finding — both scores regain 20 points — and in either case the reopened case rejoins the provisional model's open-case term until it is resolved again. This cycle can repeat; the count keeps the full history legible.

### 3.8. Supplier Qualification Scores and Automatic Suspension

Two scores travel with every supplier, both starting at 100 and both floored at 0. They are recomputed whenever a score-mutating event occurs — an adverse-reaction report, resolution, or reopening, a recall activation or closure, or the document expiry sweep — and they are also computed on read of the supplier.

The provisional score, `qualification_score_provisional`, is the early-warning figure. It starts from 100, subtracts 20 points for each confirmed finding (an adverse reaction case in `CLOSED_CONFIRMED` whose implicated unit traces back to this supplier), subtracts 15 points for each of the supplier's recalls currently `ACTIVE`, subtracts 10 points for each open adverse reaction case — those in `REPORTED`, `UNDER_INVESTIGATION`, or `REOPENED` — and subtracts 5 points for each expired-document event (a supplier document now in `EXPIRED`). The result is floored at 0.

The final score, `qualification_score_final`, is the settled figure. It starts from 100, subtracts 20 points per confirmed finding and 5 points per expired-document event, and counts nothing else: open investigations and active recalls contribute only to the provisional figure. It too is floored at 0.

The provisional score drives an automatic gate, evaluated on every score mutation: when a `QUALIFIED` supplier's `qualification_score_provisional` falls below 60, the supplier moves to `SUSPENDED` and `suspended_at` is stamped with the clock — no human decision is required. The same gate stands behind the document-expiry cascade of §3.1, and together they explain why shipments from a lapsed supplier begin failing at receipt creation and acceptance with `ERR_SUPPLIER_NOT_QUALIFIED` the moment coverage lapses. Reinstatement is the mirror image: the provisional score must be back at 60 or higher, or the attempt fails with `ERR_SUPPLIER_SCORE_BELOW_THRESHOLD` as §3.1 describes.

### 3.9. Par-Level Policies and Inventory Valuation

Replenishment policy is expressed per tissue type. A `SupplyChainAdmin` creates a policy naming a `tissue_type`, a target `par_quantity` of zero or more, and a fiscal ceiling `max_inventory_value_cents` of zero or more; negative values fail with `ERR_INVALID_REQUEST`. At most one policy per tissue type is `ACTIVE` at a time: creating a policy where one is already active supersedes the incumbent — the incumbent moves to the terminal `SUPERSEDED` state with its `version` incremented by one, and the newcomer takes over as `ACTIVE`. Because supersession destroys the reference a stale client would have acted on, creation is OCC-guarded by `expected_current_policy_version` as §2.7 specifies, and the field may be omitted only when no active policy exists for the tissue type. Threshold changes on an active policy — a new `par_quantity`, a new `max_inventory_value_cents`, or both — go through the update operation guarded by `expected_par_level_policy_version`, which increments the policy's `version` by one on success. An update naming a policy that is no longer `ACTIVE` is rejected with `ERR_INVALID_REQUEST` once the OCC check has passed.

Each policy derives three replenishment signals from live stock. `on_hand_available` counts only units of the policy's tissue type currently `AVAILABLE` — quarantined, reserved, issued, and terminal units are all excluded. `deficit` is the larger of zero and `par_quantity` minus `on_hand_available`. `needs_reorder` is true only when `on_hand_available` is strictly below `par_quantity`; sitting exactly at par means no reorder. These figures are recomputed whenever a unit status mutation touches the tissue type — excursion and recall cascades, releases, reservations, issues, returns, and sweeps all flow through them.

Valuation answers a different question — what is the on-hand stock of one tissue type worth — and is computed on read, never stored. The caller names a `tissue_type` and a `method` of `FIFO` or `WEIGHTED_AVERAGE` as query parameters (a JSON request body is accepted as a fallback for either parameter that is absent; an unrecognized `tissue_type` or `method` fails with `ERR_INVALID_REQUEST`), and the response reports `tissue_type`, `method`, `on_hand_count`, and `total_value`. Both methods share a population definition: every unit of the named tissue type whose shipment reached `ACCEPTED`, in any unit status including terminal ones, with the on-hand subset being those population units in `QUARANTINED`, `AVAILABLE`, `RESERVED`, or `ISSUED`; `on_hand_count` is the size of that subset. When the accepted population is empty, `on_hand_count` is 0 and `total_value` is 0.

The weighted-average method values every on-hand unit at the mean cost of the accepted population. The mean is the exact, unrounded quotient of the summed `unit_cost_cents` across the whole population divided by the population size. For each distinct `lot_number` present among the on-hand units, taken in ascending lot order, a lot line value is formed by multiplying that unrounded mean by the number of on-hand units in the lot and rounding the product half-up to two decimal places; `total_value` is the sum of those per-lot line values. The order is pinned — round each lot line first, then sum — because rounding a single product of the mean times the on-hand count yields a different figure whenever receipt costs differ, and that alternate order is forbidden.

The FIFO method instead assumes the oldest accepted stock is consumed first. The consumed count is the population size minus `on_hand_count`; the population is ordered by `received_at` ascending with ties broken by `created_at` ascending — never by `id` — and the first units in that order, up to the consumed count, are deemed consumed. `total_value` is then the exact integer-cent sum of the `unit_cost_cents` of the units that remain. The fiscal cap of §3.2 projects the weighted-average method, not FIFO: with each tissue type's `ACTIVE` policy, the platform computes what the weighted-average valuation would become if the shipment's units joined the population, and refuses acceptance with `ERR_INVENTORY_VALUE_CAP_EXCEEDED` whenever that projection would exceed `max_inventory_value_cents`. Tissue types without an `ACTIVE` policy are uncapped.

## 4. Endpoint Definitions

Endpoints that create a new resource — a supplier, document, shipment, reading, manual excursion, implant case, reservation, adverse reaction report, recall, or par-level policy — return `201 Created`. Endpoints that modify an existing resource, including state transitions, returns to stock, and clock advancement, return `200 OK`. The disposition-record purge returns `204 No Content` with an empty response body (no envelope). Readers reconstruct request and response bodies from the narratives in §3; this table is only an index.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock; runs document, unit, and reservation sweeps synchronously | SupplyChainAdmin |
| POST | `/tissue-bank/suppliers` | Register a supplier (starts PENDING_QUALIFICATION) | QualityManager |
| GET | `/tissue-bank/suppliers` | List suppliers; optional `status` filter | Any |
| GET | `/tissue-bank/suppliers/{id}` | Get a supplier incl. computed qualification scores | Any |
| POST | `/tissue-bank/suppliers/{id}/approve` | Qualify a supplier (documents + segregation gates) | ComplianceOfficer |
| POST | `/tissue-bank/suppliers/{id}/suspend` | Manually suspend a QUALIFIED supplier | ComplianceOfficer |
| POST | `/tissue-bank/suppliers/{id}/reinstate` | Reinstate a SUSPENDED supplier (documents + score gates) | ComplianceOfficer |
| POST | `/tissue-bank/suppliers/{id}/disqualify` | Permanently disqualify a supplier (terminal) | ComplianceOfficer |
| GET | `/tissue-bank/suppliers/{id}/documents` | List a supplier's documents; optional `doc_type` filter | Any |
| POST | `/tissue-bank/suppliers/{id}/documents` | Submit a regulatory document (closed-interval overlap rejected) | QualityManager |
| POST | `/tissue-bank/suppliers/{id}/documents/{docId}/verify` | Verify a SUBMITTED document | QualityManager |
| POST | `/tissue-bank/suppliers/{id}/documents/{docId}/reject` | Reject a SUBMITTED document | QualityManager |
| GET | `/tissue-bank/suppliers/{id}/shipments` | List shipments received from a supplier | Any |
| GET | `/tissue-bank/suppliers/{id}/recalls` | List recalls scoped to a supplier | Any |
| POST | `/tissue-bank/shipments` | Receive a shipment; mints one QUARANTINED unit per manifest line | TissueBankCoordinator |
| GET | `/tissue-bank/shipments/{id}` | Get a shipment | Any |
| POST | `/tissue-bank/shipments/{id}/accept` | Accept a RECEIVED shipment (supplier, documents, fiscal cap gates) | TissueBankCoordinator |
| POST | `/tissue-bank/shipments/{id}/reject` | Reject a RECEIVED shipment; units returned to supplier with draft dispositions | TissueBankCoordinator |
| GET | `/tissue-bank/tissue-units` | List units; filters `supplier_id`, `freezer_id`, `shipment_id`, `status`, `tissue_type`, `lot_number`, `implanted_case_id` | Any |
| GET | `/tissue-bank/tissue-units/{id}` | Get a tissue unit | Any |
| POST | `/tissue-bank/tissue-units/{id}/release` | QC-release a QUARANTINED unit to AVAILABLE | QualityManager |
| POST | `/tissue-bank/tissue-units/{id}/hold` | Manually quarantine an AVAILABLE unit (MANUAL hold) | QualityManager |
| POST | `/tissue-bank/tissue-units/{id}/issue` | Issue a unit to the OR, directly or against an ACTIVE reservation | TissueBankCoordinator |
| POST | `/tissue-bank/tissue-units/{id}/return-to-stock` | Return an unopened ISSUED unit to AVAILABLE stock | TissueBankCoordinator |
| POST | `/tissue-bank/tissue-units/{id}/discard` | Discard a QUARANTINED or EXPIRED unit (draft DESTROYED disposition) | QualityManager |
| POST | `/tissue-bank/tissue-units/{id}/return-to-supplier` | Return a QUARANTINED unit to the supplier (draft disposition) | QualityManager |
| GET | `/tissue-bank/tissue-units/{id}/reservations` | List reservations for a unit | Any |
| GET | `/tissue-bank/tissue-units/{id}/disposition-records` | List disposition records for a unit | Any |
| GET | `/tissue-bank/tissue-units/{id}/adverse-reactions` | List adverse reaction cases implicating a unit | Any |
| POST | `/tissue-bank/freezers` | Register a freezer | SupplyChainAdmin |
| GET | `/tissue-bank/freezers` | List freezers; optional `status` and `current_excursion_id` filters | Any |
| GET | `/tissue-bank/freezers/{id}` | Get a freezer incl. computed occupancy and capacity fields | Any |
| PUT | `/tissue-bank/freezers/{id}` | Reconfigure range/capacity; OCC-guarded, capacity revalidated | SupplyChainAdmin |
| POST | `/tissue-bank/freezers/{id}/readings` | Record a temperature reading; out-of-range opens/extends an excursion | TissueBankCoordinator |
| GET | `/tissue-bank/freezers/{id}/readings` | List readings for a freezer | Any |
| POST | `/tissue-bank/freezers/{id}/excursions` | Manually report an excursion (MANUAL_REPORT) with the quarantine cascade | TissueBankCoordinator |
| GET | `/tissue-bank/freezers/{id}/excursions` | List excursions for a freezer | Any |
| GET | `/tissue-bank/freezers/{id}/units` | List units stored in a freezer | Any |
| GET | `/tissue-bank/freezers/{id}/shipments` | List shipments received into a freezer | Any |
| GET | `/tissue-bank/excursions/{id}` | Get an excursion incl. computed severity fields | Any |
| POST | `/tissue-bank/excursions/{id}/investigate` | Move an OPEN excursion to UNDER_INVESTIGATION | QualityManager |
| POST | `/tissue-bank/excursions/{id}/resolve` | Resolve UNDER_INVESTIGATION with disposition RELEASE or DESTROY | QualityManager |
| GET | `/tissue-bank/excursions/{id}/readings` | List readings linked to an excursion | Any |
| POST | `/tissue-bank/implant-cases` | Schedule an implant case (OR-room overlap rejected) | ImplantingSurgeon |
| GET | `/tissue-bank/implant-cases/{id}` | Get an implant case | Any |
| POST | `/tissue-bank/implant-cases/{id}/cancel` | Cancel a SCHEDULED case (own cases only) | ImplantingSurgeon |
| POST | `/tissue-bank/implant-cases/{id}/complete` | Complete a SCHEDULED case (own cases only) | ImplantingSurgeon |
| POST | `/tissue-bank/implant-cases/{id}/record-implantation` | Record implantation of an ISSUED unit into this case | ImplantingSurgeon |
| POST | `/tissue-bank/implant-cases/{id}/reservations` | Reserve an AVAILABLE unit for this case | TissueBankCoordinator |
| GET | `/tissue-bank/implant-cases/{id}/reservations` | List reservations for a case | Any |
| GET | `/tissue-bank/implant-cases/{id}/adverse-reactions` | List adverse reactions reported on a case | Any |
| POST | `/tissue-bank/implant-cases/{id}/adverse-reactions` | Report an adverse reaction (own case; unit IMPLANTED on this case) | ImplantingSurgeon |
| POST | `/tissue-bank/reservations/{id}/release` | Manually release an ACTIVE reservation | TissueBankCoordinator |
| GET | `/tissue-bank/reservations/{id}` | Get a reservation | Any |
| POST | `/tissue-bank/recalls` | Create a recall in DRAFT | QualityManager |
| GET | `/tissue-bank/recalls/{id}` | Get a recall | Any |
| POST | `/tissue-bank/recalls/{id}/activate` | Activate a DRAFT recall; deterministic sweep over matching units | QualityManager |
| POST | `/tissue-bank/recalls/{id}/close` | Close an ACTIVE recall once no RECALL-held units remain | QualityManager |
| GET | `/tissue-bank/adverse-reactions/{id}` | Get an adverse reaction case | Any |
| POST | `/tissue-bank/adverse-reactions/{id}/investigate` | Move REPORTED/REOPENED to UNDER_INVESTIGATION | ComplianceOfficer |
| POST | `/tissue-bank/adverse-reactions/{id}/resolve` | Close UNDER_INVESTIGATION with outcome CONFIRMED or UNCONFIRMED | ComplianceOfficer |
| POST | `/tissue-bank/adverse-reactions/{id}/reopen` | Reopen a closed adverse reaction case | ComplianceOfficer |
| POST | `/tissue-bank/par-level-policies` | Create an ACTIVE policy; supersedes the incumbent (OCC-guarded) | SupplyChainAdmin |
| GET | `/tissue-bank/par-level-policies/{id}` | Get a policy incl. computed replenishment signals | Any |
| PUT | `/tissue-bank/par-level-policies/{id}` | Update an ACTIVE policy's thresholds (OCC-guarded) | SupplyChainAdmin |
| GET | `/tissue-bank/inventory/valuation` | Computed valuation for a tissue type under FIFO or WEIGHTED_AVERAGE | Any |
| GET | `/tissue-bank/disposition-records/{id}` | Get a disposition record | Any |
| POST | `/tissue-bank/disposition-records/{id}/finalize` | Finalize a DRAFT disposition record (immutable thereafter) | ComplianceOfficer |
| DELETE | `/tissue-bank/disposition-records/{id}` | Purge a FINALIZED record past its retention period | ComplianceOfficer |

## 5. Error Code Catalogue

Trigger conditions for each error live in the narratives of §2 and §3; this catalogue is only an index of identifiers to status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_SUPPLIER_NOT_FOUND` | 404 Not Found |
| `ERR_DOCUMENT_NOT_FOUND` | 404 Not Found |
| `ERR_SHIPMENT_NOT_FOUND` | 404 Not Found |
| `ERR_UNIT_NOT_FOUND` | 404 Not Found |
| `ERR_FREEZER_NOT_FOUND` | 404 Not Found |
| `ERR_EXCURSION_NOT_FOUND` | 404 Not Found |
| `ERR_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_RESERVATION_NOT_FOUND` | 404 Not Found |
| `ERR_RECALL_NOT_FOUND` | 404 Not Found |
| `ERR_ADVERSE_REACTION_NOT_FOUND` | 404 Not Found |
| `ERR_POLICY_NOT_FOUND` | 404 Not Found |
| `ERR_DISPOSITION_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_TEMP_RANGE` | 400 Bad Request |
| `ERR_INVALID_WINDOW` | 400 Bad Request |
| `ERR_DUPLICATE_VALUE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SUPPLIER_INVALID_STATE` | 409 Conflict |
| `ERR_SUPPLIER_SCORE_BELOW_THRESHOLD` | 409 Conflict |
| `ERR_DOCUMENT_INVALID_STATE` | 409 Conflict |
| `ERR_SHIPMENT_NOT_RECEIVED` | 409 Conflict |
| `ERR_SHIPMENT_NOT_ACCEPTED` | 409 Conflict |
| `ERR_UNIT_NOT_QUARANTINED` | 409 Conflict |
| `ERR_UNIT_NOT_HOLDABLE` | 409 Conflict |
| `ERR_UNIT_NOT_ISSUABLE_STATE` | 409 Conflict |
| `ERR_UNIT_NOT_ISSUED` | 409 Conflict |
| `ERR_UNIT_NOT_RESERVABLE` | 409 Conflict |
| `ERR_UNIT_NOT_DISCARDABLE` | 409 Conflict |
| `ERR_RESERVATION_NOT_ACTIVE` | 409 Conflict |
| `ERR_CASE_INVALID_STATE` | 409 Conflict |
| `ERR_CASE_OWNERSHIP_VIOLATION` | 403 Forbidden |
| `ERR_EXCURSION_INVALID_STATE` | 409 Conflict |
| `ERR_RECALL_INVALID_STATE` | 409 Conflict |
| `ERR_RECALL_UNRESOLVED_UNITS` | 409 Conflict |
| `ERR_ADVERSE_INVALID_STATE` | 409 Conflict |
| `ERR_DISPOSITION_INVALID_STATE` | 409 Conflict |
| `ERR_SUPPLIER_NOT_QUALIFIED` | 403 Forbidden |
| `ERR_REQUIRED_DOCUMENTS_NOT_VERIFIED` | 403 Forbidden |
| `ERR_UNIT_EXPIRED` | 403 Forbidden |
| `ERR_UNIT_UNDER_ACTIVE_RECALL` | 403 Forbidden |
| `ERR_FREEZER_IN_EXCURSION` | 403 Forbidden |
| `ERR_SEVERITY_REQUIRES_DESTROY` | 403 Forbidden |
| `ERR_IMPLANT_WINDOW_CLOSED` | 409 Conflict |
| `ERR_UNIT_EXPIRES_BEFORE_CASE` | 409 Conflict |
| `ERR_RETENTION_PERIOD_ACTIVE` | 409 Conflict |
| `ERR_OR_ROOM_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_DOC_VALIDITY_OVERLAP` | 409 Conflict |
| `ERR_FREEZER_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_CAPACITY_BELOW_OCCUPIED` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_RESERVATION_UNIT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_UNIT_ISSUED_TO_ANOTHER_CASE` | 422 Unprocessable Entity |
| `ERR_UNIT_NOT_IMPLANTED_ON_CASE` | 422 Unprocessable Entity |
| `ERR_INVENTORY_VALUE_CAP_EXCEEDED` | 402 Payment Required |
