# Solid-Waste Ticketing API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Solid-Waste & Landfill Scale/Ticketing API, the system of record for the gate scale and disposal operations of a permitted municipal landfill. Every truck that enters the facility is weighed in, classified by material, inspected, and either turned away or posted against a disposal cell; each posting consumes a finite, permitted quantity of airspace, charges the responsible hauler a tipping fee, and moves the facility one step closer to capacity. The API exists to keep four normally-separate concerns in continuous agreement: the physical airspace ledger (how many cubic yards remain across the facility and its individual cells), the financial ledger (how much each hauler owes and whether they remain within their credit line), the environmental posture of the site (surface methane readings and the resulting acceptance stance), and the regulatory clearance of hazardous loads (tire and asbestos profiles).

The domain is unforgiving because these concerns interact. A single posted load can fill a cell, close the facility to further intake, push a hauler past its credit limit and suspend the account, and consume the manifest that authorized it — all in one operation, and all of which must be exactly reversible if the ticket is later voided. Because multiple gate lanes post loads against the same shared airspace, the system must detect and reject operations computed against a stale view of the facility. This specification defines each of those behaviors precisely; the calculation and workflow rules are deliberately distributed across the business-logic narrative and must be read as a whole.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting invariants that govern every endpoint. The entire API is mounted under the `/landfill` path prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request missing either header, or presenting an unrecognized value, is rejected with `ERR_UNAUTHENTICATED`. When a recognized user attempts an operation their role is not permitted to perform, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly five roles: `FacilityAdmin`, `GateOperator`, `EnvironmentalOfficer`, `BillingClerk`, and `Hauler`.

- A `FacilityAdmin` configures the physical and commercial infrastructure — facilities, cells, and hauler accounts. When `X-User-Role` is `FacilityAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- A `GateOperator` runs the gate scale: weigh-in, weigh-out, inspection, posting, and voiding. When `X-User-Role` is `GateOperator`, `X-User-ID` is an opaque operator identifier. The server records it where a transition writes it — specifically as `inspected_by` on a `Ticket` when the operator inspects a load — but it is never compared to any entity's `id`.
- An `EnvironmentalOfficer` makes special-waste decisions, records gas readings, and schedules disposal windows. When `X-User-Role` is `EnvironmentalOfficer`, `X-User-ID` is an opaque operator identifier. The server records it as `decided_by` on a `SpecialWasteApproval` when the officer decides an approval, but does not compare it to any entity's `id`.
- A `BillingClerk` generates settlement invoices and records payments. When `X-User-Role` is `BillingClerk`, `X-User-ID` is an opaque operator identifier not compared to any entity's `id`.
- A `Hauler` is a hauler company acting strictly for its own account. When `X-User-Role` is `Hauler`, `X-User-ID` is the `id` of the acting `HaulerAccount`; ownership checks on any resource that references a hauler account compare that resource's `hauler_account_id` to `X-User-ID`. A `Hauler` attempting to create or submit a manifest, open a payment, or read a resource that belongs to a different hauler account is rejected with `ERR_NOT_RESOURCE_OWNER`. This ownership check applies to the hauler-owned operations: manifest creation, manifest submission, and payment creation.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, may not be smaller than 1, and may not exceed 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific endpoint states otherwise, list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Most resources carry a standard set of system-managed fields:

- `id` — a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, set once when the resource is first created.
- `updated_at` — an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version` — an integer that starts at 1 on creation and increments by 1 on every mutation. It underpins the optimistic-concurrency mechanism described in §2.7.

There is one exception. A `GasReading` is an append-only event record: it carries only `id` and `created_at`. It has neither an `updated_at` nor a `version` field, because a reading is never modified after it is recorded. All other resources — `Facility`, `Cell`, `HaulerAccount`, `Manifest`, `SpecialWasteApproval`, `Ticket`, `DisposalWindow`, `ScaleReservation`, `Invoice`, and `Payment` — carry the full set of four common fields.

### 2.5. Nested Resource Retrieval and Referential Validation

Many endpoints address a resource through a hierarchical path (for example, a cell's disposal windows are addressed beneath the cell, and a manifest's approvals beneath the manifest). When a path contains more than one identifier, the system validates existence strictly left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource. The same left-to-right rule extends to foreign-key references supplied in a request body: any referenced facility, hauler account, manifest, cell, or invoice that does not exist yields `ERR_NOT_FOUND` before any business rule is evaluated.

### 2.6. Monetary and Airspace Precision

All monetary amounts in the system are integers denominated in whole cents; field names ending in `_cents` are never fractional. Wherever a fee computation produces a fractional cent, the result is rounded half up to the nearest whole cent. Each rounding step in the tipping-fee and invoice-total calculations is pinned to a specific point in the evaluation order (see §3.4 and §3.9); rounding is applied at exactly those points and nowhere else.

Airspace quantities are expressed in cubic yards. The airspace a landfilled ticket consumes is rounded half up to two decimal places. Diversion rates are expressed as a fraction rounded half up to four decimal places, and are reported as 0 whenever the denominator would be zero (see §2.9).

### 2.7. Optimistic Concurrency on Facility Airspace

Because several gate lanes may post loads against the same facility at once, posting is guarded by optimistic concurrency keyed on the facility's `version`. The post-load operation requires an `expected_facility_version` field in its request body, carrying the facility `version` the operator last observed. If `expected_facility_version` does not equal the facility's current `version`, the post is rejected with `ERR_STALE_FACILITY_VERSION` (HTTP 412): another post has already consumed airspace and advanced the facility's `version` since this operator last read it, so this operator's view of remaining airspace and posture is out of date. Only the post-load operation takes this version field; no other endpoint requires or accepts it.

Each successful post and each void of a posted ticket increments `Facility.version` by exactly 1, which is what makes a subsequent stale post detectable.

### 2.8. Airspace, Cell Fill, and Facility Posture Consistency

The facility and its cells form a single airspace ledger that must remain internally consistent after every mutation. A `Facility` is permitted a fixed `total_airspace_cubic_yards`. Its `consumed_airspace_cubic_yards` is the sum of `consumed_cubic_yards` across all of its cells, and its `remaining_airspace_cubic_yards` is `total_airspace_cubic_yards` minus `consumed_airspace_cubic_yards`. Each `Cell` has a fixed `capacity_cubic_yards`; its `consumed_cubic_yards` is the airspace of posted tickets assigned to it, and its `remaining_cubic_yards` is `capacity_cubic_yards` minus `consumed_cubic_yards`.

When a mutation changes a cell's consumption, the effects cascade upward. If a cell's `consumed_cubic_yards` reaches or exceeds its `capacity_cubic_yards`, the cell's `status` moves from `OPEN` to `FULL`; when a later compensation frees airspace so that `remaining_cubic_yards` becomes greater than 0, a `FULL` cell returns to `OPEN`. Any change to cell fill recomputes the parent facility's consumed and remaining airspace and its `acceptance_posture` (§2.9). Every such parent recomputation is a genuine mutation of the facility: it refreshes `updated_at` and increments `version`. A cell also carries a `fill_sequence`, a monotone per-facility counter assigned when the cell is created, which fixes the fill order (see §3.6); its terminal `status` is `CLOSED`.

### 2.9. Gas Monitoring, Diversion, and Acceptance Posture

A facility's environmental posture is derived, never set directly. Each `GasReading` records a `methane_ppm` and the `reading_at` time it was taken, and the system classifies it into a `resulting_gas_status` at creation. The facility's own `latest_methane_ppm` is the `methane_ppm` of the most recent reading, where "most recent" means the greatest `reading_at`, breaking ties by the greatest `created_at`; with no readings on record, `latest_methane_ppm` is 0. From that value the facility's `gas_status` is `EXCEEDANCE` when the concentration is at least 500 ppm, `ELEVATED` when it is at least 200 ppm but below 500, and `NORMAL` below 200 ppm. Each individual reading's `resulting_gas_status` is classified by the same three-way threshold on its own `methane_ppm`.

The facility's `acceptance_posture` is then derived in strict priority order: if `gas_status` is `EXCEEDANCE`, the posture is `CLOSED`; otherwise, if `remaining_airspace_cubic_yards` is at most 0, the posture is `CLOSED`; otherwise, if `remaining_airspace_cubic_yards` is at most ten percent of `total_airspace_cubic_yards`, the posture is `RESTRICTED`; otherwise the posture is `OPEN`. The posture and gas status are recomputed after every post, void, and gas reading, and are reflected whenever the facility is fetched.

The facility also reports two diversion rates, each the ratio of diverted tonnage to total tonnage over a set of the facility's tickets, counting only tickets whose `net_weight_tons` has been set. For each rate, the denominator is the sum of `net_weight_tons` over the tickets in scope and the numerator is the sum of `net_weight_tons` over those of them that are diverted; the rate is that quotient rounded half up to four decimal places, or 0 when the denominator is zero. The forward-looking `diversion_rate_provisional` counts tickets in either `INSPECTED` or `POSTED` status, while the actual `diversion_rate_final` counts only `POSTED` tickets.

### 2.10. Hauler Credit and Balance

Each `HaulerAccount` has a `credit_limit_cents` ceiling and a running `balance_cents` of outstanding tipping charges, which starts at 0. Posting a ticket adds its final tipping fee to the balance; voiding a posted ticket and paying an invoice both reduce it. Account `status` is machine-managed: an `ACTIVE` account is auto-suspended to `SUSPENDED` the moment its `balance_cents` reaches or exceeds `credit_limit_cents`, and a `SUSPENDED` account is auto-reactivated to `ACTIVE` as soon as its `balance_cents` falls below `credit_limit_cents`. `CLOSED` is a terminal account status. A suspended hauler cannot back a new manifest submission (§3.2).

### 2.11. Validation Ordering and Error Precedence

When several conditions could reject one request, they are evaluated in a fixed priority order so that the returned error is deterministic:

1. Authentication — headers present and recognized, else `ERR_UNAUTHENTICATED` (401).
2. Authorization — the acting role is permitted for the operation, else `ERR_UNAUTHORIZED` (403).
3. Body validation — required fields present, enums valid, weights and cents non-negative, and any `window_end` strictly greater than its `window_start`; otherwise `ERR_VALIDATION` (422).
4. Existence — path and foreign-key resources exist, checked left to right, else `ERR_NOT_FOUND` (404).
5. Ownership — an `entity_backed` `Hauler` acts only on its own account, manifest, or invoice, else `ERR_NOT_RESOURCE_OWNER` (403).
6. State — the target resource is in a valid state for the requested transition, else `ERR_INVALID_STATE` (409).
7. Facility version — on post, `expected_facility_version` matches `Facility.version`, else `ERR_STALE_FACILITY_VERSION` (412).
8. Segregation of duties — on post, the posting operator differs from `inspected_by`, else `ERR_SEGREGATION_OF_DUTIES` (409).
9. Posture and clearance safety — facility not `CLOSED`, special-waste manifest cleared, hauler not suspended, yielding `ERR_FACILITY_CLOSED`, `ERR_SPECIAL_WASTE_NOT_APPROVED`, or `ERR_HAULER_SUSPENDED` (all 409) as applicable.
10. Referential integrity — a ticket's manifest belongs to the same hauler as the ticket, else `ERR_MANIFEST_MISMATCH` (409).
11. Temporal conflicts — scale-reservation and disposal-window scheduling conflicts, yielding `ERR_LANE_OCCUPIED` or `ERR_WINDOW_CONFLICT` (409).
12. Weight and airspace — weigh-out net weight positive and tare at most gross, and at least one open cell with sufficient airspace on post, yielding `ERR_EMPTY_LOAD`, `ERR_INVALID_WEIGHT`, or `ERR_NO_AIRSPACE` (409).
13. Fiscal — on post, the hauler's balance plus this fee stays within the credit limit, else `ERR_CREDIT_LIMIT_EXCEEDED` (402).

A given endpoint applies whichever of these checks are relevant to it, but always in this relative order, so that (for example) a stale facility version surfaces before a segregation-of-duties conflict, which in turn surfaces before an airspace or credit rejection.

## 3. Business Logic & Workflows

### 3.1. Facility, Cell, and Hauler Account Setup

A `FacilityAdmin` establishes the operating environment. Creating a facility requires a `name` and the permitted `total_airspace_cubic_yards`; the new facility opens with `consumed_airspace_cubic_yards` at 0, `latest_methane_ppm` at 0, `gas_status` at `NORMAL`, `acceptance_posture` at `OPEN`, both `diversion_rate_provisional` and `diversion_rate_final` at 0, and `version` at 1. Fetching a facility returns those computed values live — its posture, gas status, remaining airspace, and both diversion rates are recomputed on read.

Under a facility, the same administrator creates cells, each with a `name` and a `capacity_cubic_yards`. A new cell starts with `consumed_cubic_yards` at 0 and `status` `OPEN`, and is stamped with a `fill_sequence` drawn from a monotone counter maintained per facility, so that every cell in a facility has a distinct fill order. A cell's `facility_id` ties it to its parent; cells may be listed under their facility or fetched individually, exposing `remaining_cubic_yards` as a computed value.

Separately, the administrator opens hauler accounts, each created with a `name` and a `credit_limit_cents`. A new account begins with `balance_cents` at 0 and `status` `ACTIVE`. Fetching a hauler account returns its running balance.

### 3.2. Manifests and Special-Waste Clearance

A `Hauler` declares an inbound load ahead of arrival by creating a manifest against its own account. Manifest creation takes the `hauler_account_id`, the `declared_material`, and the `declared_weight_tons`, and the new manifest begins in `DRAFT`. The `declared_material` is one of `MSW`, `CONSTRUCTION_DEBRIS`, `GREEN_WASTE`, `CLEAN_WOOD`, `TIRE`, or `ASBESTOS`. The system derives `is_special_waste` as true exactly when the declared material is `TIRE` or `ASBESTOS`, and sets `special_waste_cleared` to false initially.

To make a manifest usable at the gate, the hauler submits it, advancing `DRAFT → SUBMITTED`. Submission is a cross-entity guard: it is permitted only while the backing hauler account is `ACTIVE`; a submission attempted while the account is `SUSPENDED` is rejected with `ERR_HAULER_SUSPENDED`. A manifest reaches `CONSUMED` automatically when a ticket that references it is posted, and reaches `CANCELLED` automatically if the hauler account is closed while the manifest is still `SUBMITTED`.

Special waste requires environmental clearance before it can be landfilled. On a manifest, a `Hauler` or an `EnvironmentalOfficer` opens a special-waste approval, supplying the `waste_type` (`TIRE` or `ASBESTOS`) and a `profile_ref` pointing to the waste-profile document; the approval starts in `PENDING`. Only an `EnvironmentalOfficer` decides it, supplying a `decision` of either `APPROVE` or `DENY` and an optional `decision_note`. A `decision` of `APPROVE` advances `PENDING → APPROVED`, records the officer's identity in `decided_by`, stores any supplied `decision_note`, and sets the parent manifest's `special_waste_cleared` to true — clearing that manifest for special-waste posting. A `decision` of `DENY` advances `PENDING → DENIED`, likewise records `decided_by` and any `decision_note`, but leaves `special_waste_cleared` false, so a tire or asbestos ticket bound to that manifest can never be posted. The approval carries its own `manifest_id` linking it to its parent, and a manifest's approvals may be listed beneath it.

### 3.3. Gate Scale-In: Ticket Creation and the Provisional Estimate

When a truck reaches the scale, a `GateOperator` creates a ticket capturing the gross weigh-in. Ticket creation supplies the `facility_id`, the `hauler_account_id`, the gate-classified `material` (one of `MSW`, `CONSTRUCTION_DEBRIS`, `GREEN_WASTE`, `CLEAN_WOOD`, `TIRE`, or `ASBESTOS`), the scale-in `gross_weight_tons`, and — for special-waste materials, required; otherwise optional — a `manifest_id`. The new ticket enters `CREATED`, with `cell_id`, `invoice_id`, `tare_weight_tons`, `net_weight_tons`, `tipping_fee_cents`, and `posted_airspace_cy` all still unset.

At creation the system computes `estimated_fee_cents`, a provisional tipping fee, using the declared weight rather than a measured net weight: it uses the linked manifest's `declared_weight_tons` when a manifest is referenced, and otherwise the ticket's own `gross_weight_tons`. The provisional estimate ignores gas — it always uses a gas multiplier of exactly 1.00 — but is otherwise the same tiered computation described for the final fee in §3.4. A ticket also derives `is_diverted` as true exactly when its `material` is `GREEN_WASTE` or `CLEAN_WOOD`; diverted materials are recycled and consume no airspace.

### 3.4. Weigh-Out and Final Fee Determination

After tipping, the truck returns to the scale and the same operator records the tare, driving `CREATED → WEIGHED`. Weigh-out supplies the `tare_weight_tons`. Two preconditions guard it: the tare may not exceed the gross weight, otherwise the request is rejected with `ERR_INVALID_WEIGHT`; and the net weight — `gross_weight_tons` minus `tare_weight_tons` — must be strictly greater than zero, otherwise the load is treated as empty and rejected with `ERR_EMPTY_LOAD`. On success the system sets `net_weight_tons` to gross minus tare, re-derives `is_diverted` from the material, and computes the final `tipping_fee_cents`.

The final fee is a tiered, material-dependent computation evaluated in a strictly pinned order. All amounts are whole cents.

- **Weight fee.** Each material has a marginal rate schedule stated in cents per ton. `MSW` is charged at 4500 cents per ton for the portion of the weight up to 5 tons and 3800 cents per ton for the portion above 5 tons. `CONSTRUCTION_DEBRIS` is a flat 5200 cents per ton, `GREEN_WASTE` a flat 2000 cents per ton, `CLEAN_WOOD` a flat 1800 cents per ton, `TIRE` a flat 9000 cents per ton, and `ASBESTOS` a flat 15000 cents per ton. The raw weight fee is the sum, over each rate band, of the tonnage falling within that band multiplied by the band's rate; only the portion of the weight that exceeds a band's lower bound contributes, and each band contributes at most up to its upper bound. This raw weight fee is rounded half up to a whole number of cents first, before anything else is applied. For the final fee this weight is the ticket's `net_weight_tons`; for the provisional estimate of §3.3 it is the declared or gross weight instead.
- **Gas multiplier.** A multiplier is then applied to the rounded weight fee. For the final fee, the multiplier is 1.10 when — and only when — the facility's live `gas_status` is `ELEVATED`, and 1.00 otherwise; for the provisional estimate the multiplier is always 1.00. The weight fee multiplied by this gas multiplier is rounded half up to whole cents, after the multiplier is applied.
- **Special surcharge.** A flat surcharge is added: 5000 cents for `TIRE`, 20000 cents for `ASBESTOS`, and nothing for any other material.
- **Diversion rebate.** For the diverted materials `GREEN_WASTE` and `CLEAN_WOOD`, a rebate equal to twelve percent of the rounded weight fee (rounded half up to whole cents) is computed; for every other material the rebate is zero. The rebate is derived from the weight fee itself, not from the gas-adjusted amount.
- **Combination.** The subtotal is the gas-adjusted weight fee, plus the special surcharge, minus the diversion rebate. The final fee is the greater of that subtotal and a floor of 2500 cents — the minimum tipping fee — which is applied last.

The final fee lands in `tipping_fee_cents`; the provisional estimate produced at creation remains in `estimated_fee_cents`.

### 3.5. Load Inspection and Segregation of Duties

A weighed load is inspected before it can be posted. A `GateOperator` records an inspection `result` on the ticket. When the `result` is a pass, the ticket advances `WEIGHED → INSPECTED` and the inspecting operator's identity is written to `inspected_by`. When the `result` is a reject, the ticket advances `WEIGHED → REJECTED`: the supplied `reject_reason` is recorded, no airspace is consumed, no hauler charge is raised, and any linked manifest is left untouched in `SUBMITTED`. A rejected ticket is terminal. These are the two divergent outcomes from the `WEIGHED` state — a pass carries the load forward to posting, a reject turns it away for good — and each is a deliberate branch with its own effects.

The `inspected_by` value recorded here is what enforces segregation of duties at posting time (§3.6): the operator who posts a load must not be the operator who inspected it.

### 3.6. Posting the Load: Cell Selection, Airspace, and Credit

Posting is the pivotal operation. A `GateOperator` posts an inspected ticket, advancing `INSPECTED → POSTED`, and must supply `expected_facility_version` (§2.7). Posting is guarded by an ordered battery of preconditions, each with its own rejection:

- The posting operator's `X-User-ID` must differ from the ticket's `inspected_by`; a match is rejected with `ERR_SEGREGATION_OF_DUTIES`.
- `expected_facility_version` must equal the facility's current `version`, otherwise `ERR_STALE_FACILITY_VERSION`.
- The facility's `acceptance_posture` must not be `CLOSED`, otherwise `ERR_FACILITY_CLOSED`.
- If the ticket's `material` is `TIRE` or `ASBESTOS`, the ticket must reference a `manifest_id` whose manifest has `special_waste_cleared` equal to true, otherwise `ERR_SPECIAL_WASTE_NOT_APPROVED`.
- If the ticket references a manifest at all, that manifest's `hauler_account_id` must equal the ticket's `hauler_account_id`, otherwise `ERR_MANIFEST_MISMATCH`.
- For a landfilled (non-diverted) material, there must be at least one `OPEN` cell in the facility whose `remaining_cubic_yards` is at least the airspace this load will consume, otherwise `ERR_NO_AIRSPACE`.
- The hauler's `balance_cents` plus this ticket's `tipping_fee_cents` must not exceed the hauler's `credit_limit_cents`, otherwise `ERR_CREDIT_LIMIT_EXCEEDED`.

The airspace this load consumes, `posted_airspace_cy`, is the ticket's `net_weight_tons` multiplied by 1.5 and rounded half up to two decimal places for a landfilled material, and exactly 0 for a diverted material (which is recycled and occupies no cell).

When all preconditions pass, the post commits a cascade of effects. The system selects the fill cell: among the facility's `OPEN` cells whose `remaining_cubic_yards` is at least `posted_airspace_cy`, it picks the one with the lowest `fill_sequence` (because `fill_sequence` is a monotone per-facility counter, it never ties, so the choice is unambiguous); an empty candidate set is the `ERR_NO_AIRSPACE` rejection above. The chosen cell's `id` is stored in the ticket's `cell_id`, and that cell's `consumed_cubic_yards` is increased by `posted_airspace_cy`. If the cell's `consumed_cubic_yards` then reaches or exceeds its `capacity_cubic_yards`, the cell transitions `OPEN → FULL`; and if that newly full cell leaves the facility with no `OPEN` cell still holding remaining airspace, the facility's `acceptance_posture` is recomputed to `CLOSED`. The facility's `consumed_airspace_cubic_yards` is recomputed and its `version` is incremented by 1. The hauler's `balance_cents` is increased by the ticket's `tipping_fee_cents`, and if the balance now reaches or exceeds the credit limit the account transitions `ACTIVE → SUSPENDED`. Finally, if the ticket referenced a manifest, that manifest transitions `SUBMITTED → CONSUMED`.

### 3.7. Voiding and Compensating Reversals

A ticket may be voided by a `GateOperator`, and what a void does depends on how far the ticket had progressed. Voiding a ticket still in `CREATED` — abandoned before weighing — simply advances `CREATED → VOIDED` with no compensation, since nothing was consumed or charged.

Voiding a `POSTED` ticket advances `POSTED → VOIDED` and reverses every effect of the post, conserving both airspace and balance. The cell's `consumed_cubic_yards` is decreased by the ticket's `posted_airspace_cy`; if that cell was `FULL` and its `remaining_cubic_yards` is now greater than 0, it transitions `FULL → OPEN`. The facility's `consumed_airspace_cubic_yards` and `acceptance_posture` are recomputed and its `version` is incremented by 1. The hauler's `balance_cents` is decreased by the ticket's `tipping_fee_cents`, and if the balance is now below the credit limit while the account is `SUSPENDED`, the account transitions back `SUSPENDED → ACTIVE`. Both `VOIDED` and `REJECTED` are terminal ticket states.

### 3.8. Scheduling: Scale Reservations and Disposal Windows

Two scheduling resources coordinate physical access to the site, and they use deliberately different interval semantics.

A scale reservation books a gate lane for a weigh window. A `Hauler` or a `GateOperator` reserves a lane on a facility by supplying a `lane_number`, a `truck_ref`, and the window bounds `window_start` and `window_end`; the reservation opens in `RESERVED`. The reserved window is treated as a half-open interval — inclusive of `window_start` and exclusive of `window_end` — so two reservations that merely abut (one ending exactly when the next begins) do not conflict. A reservation is rejected with `ERR_LANE_OCCUPIED` if its window overlaps another `RESERVED` window on the same facility and the same `lane_number`, and is rejected with `ERR_FACILITY_CLOSED` if the facility's posture is `CLOSED`. Reservations may be listed for a facility, optionally filtered by `lane_number`, and a reservation's terminal status is `CANCELLED`.

A disposal window schedules a placement slot for special waste on a specific cell. An `EnvironmentalOfficer` schedules a window on a cell with a `waste_type` (`TIRE` or `ASBESTOS`) and the bounds `window_start` and `window_end`; it opens in `SCHEDULED`. Unlike a scale reservation, a disposal window is a closed interval — both `window_start` and `window_end` are inclusive — so a new window that touches or overlaps another window already scheduled on the same cell is rejected with `ERR_WINDOW_CONFLICT`. In all scheduling requests, body validation still requires `window_end` to be strictly greater than `window_start`, failing with `ERR_VALIDATION` otherwise. A disposal window's terminal status is `CANCELLED`, and windows may be listed for their cell.

### 3.9. Billing, Settlement, and Payment

A `BillingClerk` closes the loop by settling posted loads. Generating an invoice takes the `hauler_account_id` and sweeps that hauler's billable tickets — those in `POSTED` status that have not already been placed on an invoice — onto a new invoice in `ISSUED` status. The swept tickets are ordered by `created_at` ascending and recorded on the invoice as `line_ticket_ids`, with `line_count` giving their number; each swept ticket has its `invoice_id` set to the new invoice. If the hauler has no billable tickets, the invoice cannot be generated and the request is rejected with `ERR_NO_BILLABLE_TICKETS`.

The invoice records two money fields. The `tipping_subtotal_cents` is the plain sum of `tipping_fee_cents` across the line tickets — the amount that will be released from the hauler's balance when the invoice is paid. The billed `total_cents` layers on the host fee of 8.75 percent, with the rounding order pinned: for each line ticket, the ticket's `tipping_fee_cents` is multiplied by 1.0875 and rounded half up to whole cents, and only then are those per-line amounts summed. (Summing first and rounding once at the end is explicitly not used.) The invoice's `amount_paid_cents` starts at 0.

A `BillingClerk` or the owning `Hauler` records a payment against an invoice by supplying an `amount_cents` and a `method` (one of `ACH`, `CARD`, or `CHECK`). Each payment is tied to its invoice by `invoice_id`, and the invoice's `amount_paid_cents` is recomputed as the sum of `amount_cents` over its payments. When the cumulative `amount_paid_cents` reaches the invoice's `total_cents`, the invoice transitions `ISSUED → PAID`, and a cascade releases the hauler's exposure: for each line ticket the hauler's `balance_cents` is decreased by that ticket's `tipping_fee_cents`, and if the resulting balance is below the credit limit while the account is `SUSPENDED`, the account transitions back to `ACTIVE`. An invoice may instead be voided from `ISSUED → VOID` when no payments have been applied, which releases its line tickets by clearing their `invoice_id`. `PAID` and `VOID` are terminal invoice states.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a distinct resource to a collection return `201 Created`. Operations that modify an existing resource — including all state transitions such as submit, decide, weigh-out, inspect, post, void, and payment settlement effects — return `200 OK`, except that recording a payment creates a new `Payment` resource and therefore returns `201 Created`. Reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/landfill/facilities` | Create a landfill facility | FacilityAdmin |
| GET | `/landfill/facilities/{id}` | Get a facility with computed posture, gas status, and diversion rates | FacilityAdmin, GateOperator, EnvironmentalOfficer, BillingClerk, Hauler |
| POST | `/landfill/facilities/{id}/cells` | Create a cell under a facility | FacilityAdmin |
| GET | `/landfill/facilities/{id}/cells` | List cells of a facility | FacilityAdmin, GateOperator, EnvironmentalOfficer |
| GET | `/landfill/cells/{id}` | Get a cell | FacilityAdmin, GateOperator, EnvironmentalOfficer |
| POST | `/landfill/hauler-accounts` | Create a hauler account | FacilityAdmin |
| GET | `/landfill/hauler-accounts/{id}` | Get a hauler account with running balance | FacilityAdmin, BillingClerk, Hauler |
| POST | `/landfill/manifests` | Create an inbound manifest (DRAFT) | Hauler |
| GET | `/landfill/manifests/{id}` | Get a manifest | Hauler, GateOperator, EnvironmentalOfficer |
| GET | `/landfill/manifests` | List manifests, optionally filtered by hauler | Hauler, GateOperator, EnvironmentalOfficer |
| POST | `/landfill/manifests/{id}/submit` | Submit a manifest for acceptance | Hauler |
| POST | `/landfill/manifests/{id}/special-waste-approvals` | Open a special-waste approval request on a manifest | Hauler, EnvironmentalOfficer |
| GET | `/landfill/manifests/{id}/special-waste-approvals` | List special-waste approvals of a manifest | Hauler, EnvironmentalOfficer, GateOperator |
| POST | `/landfill/special-waste-approvals/{id}/decide` | Approve or deny a special-waste request | EnvironmentalOfficer |
| POST | `/landfill/tickets` | Scale-in: create a ticket with gross weight | GateOperator |
| GET | `/landfill/tickets/{id}` | Get a ticket | GateOperator, EnvironmentalOfficer, BillingClerk, Hauler |
| GET | `/landfill/tickets` | List tickets with FK filters | GateOperator, EnvironmentalOfficer, BillingClerk, Hauler |
| POST | `/landfill/tickets/{id}/weigh-out` | Scale-out: record tare, compute net weight and final fee | GateOperator |
| POST | `/landfill/tickets/{id}/inspect` | Load inspection: pass advances, reject terminates | GateOperator |
| POST | `/landfill/tickets/{id}/post` | Post the load: select cell, consume airspace, charge hauler | GateOperator |
| POST | `/landfill/tickets/{id}/void` | Void a ticket (compensating reversal) | GateOperator |
| POST | `/landfill/facilities/{id}/gas-readings` | Record a methane reading | EnvironmentalOfficer |
| GET | `/landfill/facilities/{id}/gas-readings` | List gas readings of a facility | EnvironmentalOfficer, FacilityAdmin |
| POST | `/landfill/cells/{id}/disposal-windows` | Schedule a special-waste disposal window on a cell | EnvironmentalOfficer |
| GET | `/landfill/cells/{id}/disposal-windows` | List disposal windows of a cell | EnvironmentalOfficer, FacilityAdmin |
| POST | `/landfill/facilities/{id}/scale-reservations` | Reserve a gate scale lane window | Hauler, GateOperator |
| GET | `/landfill/facilities/{id}/scale-reservations` | List scale reservations of a facility | Hauler, GateOperator, FacilityAdmin |
| POST | `/landfill/invoices` | Generate a settlement invoice for a hauler's posted tickets | BillingClerk |
| GET | `/landfill/invoices/{id}` | Get an invoice | BillingClerk, Hauler |
| GET | `/landfill/invoices` | List invoices, optionally filtered by hauler | BillingClerk, Hauler |
| POST | `/landfill/invoices/{id}/payments` | Record a payment against an invoice | BillingClerk, Hauler |
| GET | `/landfill/invoices/{id}/payments` | List payments of an invoice | BillingClerk, Hauler |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_VALIDATION` | 422 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_FACILITY_VERSION` | 412 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_FACILITY_CLOSED` | 409 |
| `ERR_SPECIAL_WASTE_NOT_APPROVED` | 409 |
| `ERR_HAULER_SUSPENDED` | 409 |
| `ERR_MANIFEST_MISMATCH` | 409 |
| `ERR_LANE_OCCUPIED` | 409 |
| `ERR_WINDOW_CONFLICT` | 409 |
| `ERR_EMPTY_LOAD` | 409 |
| `ERR_INVALID_WEIGHT` | 409 |
| `ERR_NO_AIRSPACE` | 409 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 |
| `ERR_NO_BILLABLE_TICKETS` | 409 |
