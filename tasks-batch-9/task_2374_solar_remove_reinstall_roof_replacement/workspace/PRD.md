# Solar Reroof Coordination API — Product Requirements Document

## 1. Introduction

When a homeowner replaces a roof that already carries a photovoltaic array, the array has to come off and go back on. That sounds like a single job; in practice it is a negotiation between at least three parties who do not report to one another — the roofer who owns the deck, the solar owner who owns the building, and, on a leased or power-purchase system, a third-party system owner who owns the hardware and the revenue it produces. SunSystem Technology sits in the middle of that triangle as coordinator, and the cost of getting it wrong is not measured in inconvenience: an array de-energized without a verified lockout is a safety incident, a module stored past its warranty window is an uninsured asset, and a structural deck repair discovered after the permit was approved can invalidate that permit and every inspection already passed under it.

This document specifies the Solar Reroof Coordination API, mounted under `/reroof`. The API is the system of record for the whole remove-and-reinstall sequence: securing consent from every party before a single conductor is opened, de-energizing and isolating each circuit, removing modules and optimizers into labeled and capacity-limited storage, recording what the bare deck actually looks like, scoping and signing off attachment and flashing upgrades under segregation of duties, re-permitting and re-inspecting where the authority having jurisdiction demands it, sourcing replacements for damaged hardware under mismatched-model rules, notifying the manufacturer so module warranties survive the round trip, and finally reconciling the production the array did not generate while it sat in a bin — into a lease or power-purchase credit that is reserved up front and settled against what actually happened.

Two design commitments run through everything below. First, the system is **conservative about physical risk**: a project accumulates a derived safety posture from its open findings, rejected permits, failed inspections and weather aborts, and that posture gates every field operation regardless of who requests it. Second, the system is **honest about money**: every cent of downtime credit the project ever authorizes remains accounted for in a four-account ledger whose identity is checked before settlement is allowed to proceed.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that hold across every endpoint. Unlike §3, nothing here is negotiable per workflow.

### 2.1. Coordination Identity and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the actor, and `X-User-Role`, declaring the capacity in which that actor is operating. If either header is missing or empty, or if `X-User-Role` is not one of the six roles enumerated below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well formed but the declared role is not among the roles authorized for the endpoint being called, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403). The six recognized roles are `ProjectCoordinator`, `SolarContractor`, `RoofingContractor`, `SolarOwner`, `SystemOwner`, and `AHJInspector`.

The roles differ in how `X-User-ID` is interpreted, and this distinction is what makes ownership enforceable.

- When `X-User-Role` is `ProjectCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit purposes but never compares it to any entity's `id`. A coordinator is trusted across every project.
- When `X-User-Role` is `SolarContractor`, `RoofingContractor`, `SolarOwner`, or `SystemOwner`, `X-User-ID` is the `id` of the acting `Party`; ownership checks on any resource that references a `Party` compare the resource's party foreign key to `X-User-ID`.
- When `X-User-Role` is `AHJInspector`, `X-User-ID` is the `id` of the acting `Jurisdiction`; ownership checks on any resource that references a `Jurisdiction` compare the resource's jurisdiction foreign key to `X-User-ID`.

Where a role acts on a specific resource, the ownership comparison is concrete and its failure carries `ERR_PARTY_NOT_ON_PROJECT` (HTTP 403): a consent decision requires `X-User-ID` to equal the target consent record's `party_id`; a sourcing-order review requires `X-User-ID` to equal the project's `system_owner_party_id`; a crew-driven window status change requires `X-User-ID` to equal the window's `party_id`; and an `AHJInspector` deciding a permit or recording an inspection result requires `X-User-ID` to equal the governing permit application's `jurisdiction_id`.

`ProjectCoordinator` owns the reference data (parties and jurisdictions), the project record, the consent requests, the circuit and bin registries, the permit paperwork and its inspection bookings, the crew calendar, replacement sourcing and receipt, the manufacturer warranty notice, the credit settlement, and the two test-driving capabilities. `SolarContractor` alone energizes and de-energizes circuits, registers hardware, and drives removal, storage, condition grading and reinstall. `RoofingContractor` alone records deck findings and drives their upgrade actions. `SystemOwner` alone reviews non-exact sourcing orders. `AHJInspector` alone decides permit applications and records inspection results, and only for its own jurisdiction. Advancing a crew window's status is shared by `ProjectCoordinator`, `RoofingContractor` and `SolarContractor`. Recording a consent decision is shared by `RoofingContractor`, `SolarOwner` and `SystemOwner`. Read access is broad but not universal, and §4 is authoritative on which roles may read which collection.

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

List endpoints are paginated through two query parameters. `limit` caps the number of rows returned; it defaults to 10, may be no smaller than 1 and no larger than 100. A `limit` outside that inclusive range is a schema violation and is rejected with `ERR_INVALID_REQUEST`. `offset` is the number of rows to skip and defaults to 0.

Unless a specific endpoint says otherwise, list results are ordered by `created_at` ascending.

Every list response carries `limit`, `offset`, `total_count` and `has_more` inside the envelope's `meta` object.

### 2.4. Record Identity, Timestamps and the Logical Clock

Each persisted resource receives a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp rendered as an ISO 8601 UTC instant with three fractional digits. Most resources additionally carry `updated_at`, refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by one on every mutation of that resource — including mutations that only rewrite derived fields such as a project's counters, posture or credit accounts. `Jurisdiction` is the sole exception: an authority-having-jurisdiction record is immutable once created, has no update endpoint, and carries **neither** `updated_at` **nor** `version`. It has only `id` and `created_at` alongside its own attributes.

All time in this system is logical, not wall-clock. Before any clock-setting call the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to real wall-clock time. An admin-only test-driving capability sets the logical clock to a supplied `to_iso8601` instant and answers with the resulting `current_utc`. Every deadline, backlog floor, off-roof-day count, inspection window comparison and downtime date range in this specification is measured against that logical clock; where the prose below says "the current instant", it means the logical clock's reading at the moment the request is processed.

### 2.5. Path Resolution and Cross-Aggregate Referential Integrity

Path identifiers are resolved strictly left to right, and the first identifier that does not resolve determines the 404 that comes back: `ERR_PROJECT_NOT_FOUND`, `ERR_APPROVAL_NOT_FOUND`, `ERR_CIRCUIT_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`, `ERR_FINDING_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND` or `ERR_SOURCING_ORDER_NOT_FOUND`. So a request for the inspections of a permit application that does not exist answers `ERR_PERMIT_NOT_FOUND` without ever looking at inspections.

Foreign keys arriving in a request body are resolved the same way, before any business rule runs, and an unresolvable reference produces the corresponding 404: `ERR_PROJECT_NOT_FOUND`, `ERR_PARTY_NOT_FOUND`, `ERR_JURISDICTION_NOT_FOUND`, `ERR_CIRCUIT_NOT_FOUND`, `ERR_BIN_NOT_FOUND` or `ERR_UNIT_NOT_FOUND`.

Existing but *misfiled* references are a different failure. Every entity in this system is a top-level collection under `/reroof`, so nothing prevents a client from naming a circuit, a bin or a hardware unit that belongs to some other project. Three places must refuse it with `ERR_CROSS_PROJECT_REFERENCE` (HTTP 422): registering a hardware unit whose `array_circuit_id` belongs to a different project than the one in the path, placing a unit into a storage bin whose owning project differs from the unit's, and creating a sourcing order whose `hardware_unit_id` does not belong to the `project_id` supplied on the same order.

### 2.6. Project Posture: the Derived Safety Gate

Alongside its explicit coordination `phase`, every project carries a derived `posture` that is recomputed at the end of every mutation touching the project or any of its children. It takes one of three values — `OPEN`, `RESTRICTED` or `FROZEN` — and it is evaluated in that severity order.

The posture is `FROZEN` when either of the following holds: the project has at least one deck finding whose `status` is `OPEN` and whose `severity` is `CRITICAL`, or the project has at least one permit application whose `status` is `REJECTED`.

If the project is not `FROZEN`, the posture is `RESTRICTED` when at least one of these four conditions holds: the project has a deck finding whose `severity` is `HIGH` and whose `status` is either `OPEN` or `UPGRADE_SCOPED`; the project has a permit application whose `status` is either `DRAFT` or `SUBMITTED` and whose jurisdiction has `repermit_required_for_reinstall` set to true; some inspection booked under any permit application of the project has `status` `FAILED` or `CORRECTION_REQUIRED`; or the project's `weather_abort_count` has reached two or more. Otherwise the posture is `OPEN`.

Work windows in `SUPERSEDED`, `REVOKED` or `COMPLETED` state never influence posture directly; only the running `weather_abort_count` does, and that counter is never decremented.

Posture is a gate, not merely a label. Two distinct bars exist. Operations that merely require the project not to be frozen — de-energizing or re-energizing a circuit, removing a unit, storing a unit, reinstalling a unit, scheduling a crew window, and starting a crew window — are refused with `ERR_PROJECT_POSTURE_FROZEN` (HTTP 409) while the posture is `FROZEN`. Two operations demand more, requiring the posture to be exactly `OPEN` because they restore energy or put hardware back on the roof: reinstalling a unit and re-energizing a circuit. When the posture on those two is `RESTRICTED`, the refusal is `ERR_PROJECT_POSTURE_RESTRICTED` (HTTP 409). Note the deliberate overlap: reinstall and re-energization are subject to the frozen bar first and the restricted bar second.

### 2.7. The Downtime Credit Ledger and Its Conservation Identity

A project's downtime credit is tracked in four integer cent accounts: `credit_authorized_cents` is every cent the project has ever committed to; `credit_reserved_cents` is authorized credit not yet settled or released; `credit_settled_cents` is authorized credit paid out at settlement; and `credit_released_cents` is authorized credit handed back, either because downtime turned out shorter than estimated or because authorization was withdrawn. All four start at zero. Two further computed figures, `provisional_credit_cents` and `final_credit_cents`, record the output of the two credit variants described in §3.9.

The conserved identity is that `credit_authorized_cents` always equals the sum of `credit_reserved_cents`, `credit_settled_cents` and `credit_released_cents`. Every ledger movement in this system is written as a transfer that preserves it. Reserving the provisional credit adds the same amount to both the authorized and the reserved accounts. Withdrawing authorization moves the entire reserved balance into the released account and leaves the authorized total untouched. Settlement moves the reserved balance out and recomputes the released account as the authorized total minus what was settled, topping the authorized total up first if the final figure came out higher than what was reserved.

Because no legitimate workflow can unbalance the ledger, the identity is nevertheless re-verified defensively before settlement is applied; a project whose accounts do not satisfy it is refused with `ERR_CREDIT_LEDGER_UNBALANCED` (HTTP 409). A test-driving capability exists purely so that guard is reachable: given a `project_id` and a `released_delta_cents` amount, it adds that amount to `credit_released_cents` while leaving `credit_authorized_cents`, `credit_reserved_cents` and `credit_settled_cents` untouched, and increments the project's `version`. A read-only downtime summary exposes the whole position — `downtime_days_actual`, `provisional_credit_cents`, `final_credit_cents`, `credit_authorized_cents`, `credit_reserved_cents`, `credit_settled_cents`, `credit_released_cents`, and a boolean `ledger_balanced` reporting whether the identity currently holds.

### 2.8. Money, Percentages and Rounding Discipline

Every monetary amount in this system is an integer number of whole cents; there are no fractional cents anywhere. Wherever a cent amount is derived from a real-valued product, the result is rounded half up to a whole cent, and the *number and placement* of those roundings is part of the specification, not an implementation detail — §3.6 and §3.9 pin exactly where each rounding falls.

Percentages behave differently. The watt-delta of a sourcing order (`watt_delta_pct`) and the circuit watt spread are computed to two decimal places, rounded half up; the tolerance a sourcing order applies (`tolerance_pct`) is an exact two-decimal figure assembled from published constants and needs no rounding. Comparisons against those percentages are boundary-sensitive in ways stated explicitly at each site: a watt-delta exactly equal to the tolerance is inside tolerance, and a circuit spread exactly equal to the limit is accepted.

Day counts are calendar-date differences in UTC, always whole integers, and every day comparison in the warranty rules is inclusive of the boundary.

### 2.9. Optimistic Concurrency on the Project Record

Two write operations take the project record as their concurrency parent and therefore require the client to declare which version of it they read. Both require a non-optional `expected_project_version` field in the request body carrying the client's last observed `version` of the target `ReroofProject`.

The first is creating a sourcing order. A second sourcing order against the same damaged unit is legitimate product behaviour — it supersedes the earlier quote when the distributor comes back with a different part — so the request cannot be refused on state grounds. The stale `expected_project_version` is the only signal that the writer has not yet seen the earlier order, or the change that order made to the project's warranty notice status. If the supplied `expected_project_version` does not equal the project's current `version`, the create is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412).

The second is filing the manufacturer warranty notice. Re-filing is likewise legitimate — a second notice supersedes the first when the model of record changed — so the request cannot be refused on state grounds either. Here too, a supplied `expected_project_version` that does not equal the project's current `version` is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412), which prevents a notice being filed against an outdated view of the model of record.

No other endpoint takes a version field. Endpoints not named above are processed without any optimistic-concurrency check.

### 2.10. Cascade and Reconciliation Semantics

The project record is a rolled-up view of its children, and the server keeps it aligned without being asked. Whenever a child row changes in a way that affects a derived project figure, the server recomputes that figure in the same request, refreshes the project's `updated_at` and increments its `version`. The derived counters are `registered_unit_count` (every hardware unit on the project, across all handling states), `stored_unit_count`, `reinstalled_unit_count`, `scrapped_unit_count`, `damaged_unit_count`, `open_critical_finding_count`, `scoped_upgrade_cost_cents`, `downtime_days_actual`, `warranty_preserved`, `required_approval_party_count` and `posture`. The population identity that must hold after every mutation is that `registered_unit_count` equals the number of units in `ON_ROOF` plus `REMOVED` plus `STORED` plus `REINSTALLED` plus `SCRAPPED`, and that the sum of `occupied_slots` over the project's bins equals the number of the project's units whose `handling_status` is exactly `STORED`.

Phase advancement works the same way. Several project phase transitions are evaluated by the server at the end of a child mutation rather than requested directly, and the specific evaluation points are named in §3. Because a single request can therefore mutate a child, roll up its parent, and cascade into a sibling aggregate, §3 states the secondary effects explicitly wherever they exist — the re-permitting cascade in §3.6 reaches four levels deep, and it is not optional.

### 2.11. Validation Precedence

When several rules could reject the same request, they are evaluated in a fixed order so that the returned `error_id` is deterministic. The order is:

1. Header authentication — `ERR_UNAUTHENTICATED`.
2. Role authorization for the endpoint — `ERR_ROLE_NOT_PERMITTED`.
3. Existence of every path resource, left to right — the family of 404s in §2.5.
4. Existence of every foreign key in the body — the family of 404s in §2.5.
5. Request-body schema: required fields present, enum members legal, numeric ranges respected, ISO 8601 timestamps parseable, `accepts_unit_types` a non-empty subset of `PANEL` and `OPTIMIZER`, pagination `limit` between 1 and 100 inclusive — `ERR_INVALID_REQUEST`.
6. Actor ownership for entity-backed roles — `ERR_PARTY_NOT_ON_PROJECT`.
7. Optimistic concurrency on the project — `ERR_STALE_PROJECT_VERSION`.
8. State legality of the requested transition, including the negotiation-round freshness check on a consent decision and the requirement that a permit application be `SUBMITTED` or `APPROVED` before an inspection can be booked under it — `ERR_INVALID_STATE`, `ERR_APPROVAL_ROUND_STALE`, `ERR_PERMIT_NOT_SUBMITTED` or `ERR_SETTLEMENT_NOT_READY`.
9. Circuit isolation before a unit is removed or reinstalled — `ERR_CIRCUIT_NOT_ISOLATED`.
10. The frozen-posture bar — `ERR_PROJECT_POSTURE_FROZEN`.
11. The restricted-posture bar — `ERR_PROJECT_POSTURE_RESTRICTED`.
12. Warranty notice on file before reinstall — `ERR_WARRANTY_NOTICE_MISSING`.
13. Unit serviceability before reinstall — `ERR_UNIT_NOT_SERVICEABLE`.
14. All non-scrapped units on the circuit reinstalled before re-energization — `ERR_CIRCUIT_UNITS_NOT_REINSTALLED`.
15. Cross-project reference integrity — `ERR_CROSS_PROJECT_REFERENCE`.
16. Segregation of duties on a finding completion — `ERR_SEGREGATION_OF_DUTIES`.
17. Party-type suitability of every referenced party — `ERR_PARTY_TYPE_MISMATCH`.
18. Mismatched-model waiver presence — `ERR_MODEL_MISMATCH_NOT_WAIVED`.
19. Circuit watt spread after a receipt — `ERR_CIRCUIT_WATT_SPREAD_EXCEEDED`.
20. Interval well-formedness — `ERR_INVALID_WINDOW_BOUNDS`.
21. Inspection backlog floor — `ERR_INSPECTION_BACKLOG_VIOLATION`.
22. Crew window overlap — `ERR_CREW_WINDOW_CONFLICT`.
23. Aggregate inspection slot capacity — `ERR_INSPECTION_SLOT_FULL`.
24. Bin unit-type acceptance — `ERR_BIN_UNIT_TYPE_REJECTED`.
25. Serial-number uniqueness within the project — `ERR_DUPLICATE_SERIAL`.
26. Bin-label uniqueness within the project — `ERR_DUPLICATE_BIN_LABEL`.
27. Circuit-label uniqueness within the project — `ERR_DUPLICATE_CIRCUIT_LABEL`.
28. One consent record per project-and-party pair — `ERR_DUPLICATE_APPROVAL_PARTY`.
29. Bin capacity — `ERR_BIN_CAPACITY_EXCEEDED`.
30. Upgrade budget — `ERR_UPGRADE_BUDGET_EXCEEDED`.
31. Credit ledger identity — `ERR_CREDIT_LEDGER_UNBALANCED`.

The practical consequences are worth spelling out. On a unit reinstall, five checks can fire and their relative order is fixed: circuit isolation first, then the frozen bar, then the restricted bar, then the warranty notice, then serviceability — so a unit on a non-isolated circuit of a frozen project answers `ERR_CIRCUIT_NOT_ISOLATED`, not `ERR_PROJECT_POSTURE_FROZEN`. On a crew window creation, interval well-formedness is checked before overlap, so a window whose `end_utc` precedes its `start_utc` answers `ERR_INVALID_WINDOW_BOUNDS` even if it would also have collided with another window. On an inspection booking, the backlog floor is checked before day capacity, so a date that is both too early and fully booked answers `ERR_INSPECTION_BACKLOG_VIOLATION`. And on a deck finding scope action, party-type suitability precedes the budget check, so a non-roofer attempting to scope an over-budget finding answers `ERR_PARTY_TYPE_MISMATCH`.

## 3. Business Logic & Workflows

### 3.1. The Coordination Triangle and the Authority Having Jurisdiction

Before a project exists, its participants must be on file. A coordinator registers each participant as a **Party** carrying a legal or trade `name` (non-empty, at most 200 characters), a `party_type`, and a `contact_email` that must contain an at-sign. The `party_type` is one of `ROOFER`, `SOLAR_OWNER`, `SYSTEM_OWNER` or `SOLAR_CONTRACTOR`, and it decides where in the triangle that party sits. Two scheduling attributes come with the party rather than with each job: `mobilization_buffer_minutes`, the mobilization and demobilization time the party needs on either side of any crew window, which defaults to two hours and must be between 0 and 480 minutes inclusive; and `daily_crew_capacity`, an informational crew-count-per-day figure that defaults to 1 and must be at least 1. Contractor parties also carry a `license_number`; it defaults to absent, and it is legitimately absent for solar-owner and system-owner parties, who hold no licence.

An **authority having jurisdiction** is registered separately and is immutable thereafter. It carries a `name`, a short `code` that must be uppercase alphanumeric and unique across all jurisdictions, and five policy levers that shape everything downstream. `repermit_required_for_reinstall`, when true, means a structural deck upgrade invalidates an already-approved permit and forces re-permitting before the array goes back on. `reinspection_required`, when true, means the project cannot be commissioned without a passed electrical-final inspection under an approved permit. `inspection_slots_per_day` is the aggregate number of inspections this authority will accept on a single calendar date across every permit it governs, and must be at least 1. `backlog_days`, between 0 and 90 inclusive, is how far into the future the authority's earliest bookable inspection sits. `permit_review_days`, at least 1, is how many whole days the authority takes to review a submission. Finally `expedite_fee_cents`, defaulting to zero and never negative, is the surcharge the authority charges for expedited handling.

### 3.2. Opening a Project and Winning Consent

A coordinator opens a **ReroofProject** by naming the `site_address`, the `ownership_model` — one of `HOST_OWNED`, `LEASE` or `PPA` — the array's nameplate `system_dc_kw` (strictly positive), and the four party references: `roofer_party_id`, `solar_owner_party_id`, `solar_contractor_party_id` and, conditionally, `system_owner_party_id`. Each reference must point at a party of the matching type — a `ROOFER` for the roofer slot, a `SOLAR_OWNER` for the solar-owner slot, a `SOLAR_CONTRACTOR` for the crew that will de-energize, remove and reinstall, and a `SYSTEM_OWNER` for the system-owner slot — and any mismatch is rejected with `ERR_PARTY_TYPE_MISMATCH` (HTTP 422). The system-owner slot is the interesting one: it is **required** when `ownership_model` is `LEASE` or `PPA`, and it must be **absent** when `ownership_model` is `HOST_OWNED`. Getting that pairing wrong in either direction is also `ERR_PARTY_TYPE_MISMATCH`.

Three further inputs describe the economics. `baseline_daily_kwh` (strictly positive) is the array's expected daily production and is the basis of every production-loss credit. `downtime_days_estimated` (at least 1) is the planned whole days of downtime, and is used only by the forward-looking provisional credit variant. `upgrade_budget_cents` (never negative) caps the total deck-upgrade cost the project may scope.

On creation the project's `phase` is `INTAKE` and its `posture` is `OPEN`. Its `negotiation_round` starts at 1 and its `version` at 1. `required_approval_party_count` is derived immediately: 3 when a system owner was named, otherwise 2 — this is the consent quorum. `warranty_notice_status` is derived from the ownership model: `NOT_REQUIRED` on a `HOST_OWNED` project, `PENDING` on a `LEASE` or `PPA` project. All four credit accounts and every derived counter start at zero, `warranty_preserved` starts true, and `authorized_at`, `deenergized_at` and `reenergized_at` all start absent.

Consent is collected as one **PartyApproval** row per consenting party. A coordinator opens a consent request by naming a `party_id`; the referenced party must be of type `ROOFER`, `SOLAR_OWNER` or `SYSTEM_OWNER`, and it must equal the project's corresponding party field for that type, otherwise the request is `ERR_PARTY_TYPE_MISMATCH`. At most one consent record may exist per project-and-party pair; a second attempt answers `ERR_DUPLICATE_APPROVAL_PARTY` (HTTP 409). The new record's `approval_role` is copied from the referenced party's `party_type`, its `status` is `PENDING`, its `round_recorded` is set to the project's current `negotiation_round`, its `change_request_count` is zero, its `veto_flag` is false, and `decided_at` is absent. Creating the **first** consent record on a project also advances the project from `INTAKE` to `APPROVALS_OPEN` and triggers a posture recomputation; the project must be in `INTAKE` for that advance to apply.

A consenting party then records a decision, supplying a `decision` of either `APPROVE` or `REQUEST_CHANGES` and optionally a `decision_note` capturing the rationale. Only the party the record belongs to may decide it, and the record's `round_recorded` must still equal the project's `negotiation_round`; a decision arriving against a superseded round is refused with `ERR_APPROVAL_ROUND_STALE` (HTTP 409).

An `APPROVE` decision is accepted from either `PENDING` or `CHANGES_REQUESTED`. It sets `status` to `APPROVED`, stamps `decided_at` with the current instant, and clears `veto_flag` back to false. Clearing the veto is what allows an objecting party to withdraw its objection inside the current round and let the project re-authorize. After the approval is written, the server evaluates the project's `APPROVALS_OPEN → AUTHORIZED` advance: when the count of the project's consent records whose `status` is `APPROVED` **and** whose `round_recorded` equals the project's current `negotiation_round` equals `required_approval_party_count`, the project stamps `authorized_at` with the current instant, moves to `AUTHORIZED`, and recomputes its posture. That same evaluation then re-checks the `AUTHORIZED → DEENERGIZED` advance, which matters on re-entry: if authorization had previously been withdrawn while every circuit was already `ISOLATED`, re-authorizing carries the project straight back through to `DEENERGIZED`.

A `REQUEST_CHANGES` decision is accepted from `PENDING` or `APPROVED`. It sets `status` to `CHANGES_REQUESTED`, increments that record's `change_request_count` by one, and stamps `decided_at`. When the deciding record's `approval_role` is `SYSTEM_OWNER`, it also sets that record's `veto_flag` to true. Recording a change request always drives the negotiation-round cascade: the project's `negotiation_round` increases by one, and because the round advanced, **every other** consent record on the project whose `status` is `APPROVED` is reset to `PENDING` with its `round_recorded` updated to the new round and its `decided_at` cleared. A sibling record already sitting in `CHANGES_REQUESTED` when the round advances is likewise reset to `PENDING` with the new `round_recorded` and its `veto_flag` cleared. The objecting record itself is the exception: after the cascade has incremented the round, its own `round_recorded` is set to the new `negotiation_round` so that it remains current and can withdraw its objection. Posture is then recomputed. When the project was in `APPROVALS_OPEN` this is a self-cycle — the phase stays `APPROVALS_OPEN`, but every prior consent is void.

The `SYSTEM_OWNER` veto is stronger, and it reaches a project that was already past consent. When a change request lands on a consent record whose `approval_role` is `SYSTEM_OWNER` and the project is in `AUTHORIZED`, the veto withdraws authorization: alongside the record's own `status`, `veto_flag` and `change_request_count` updates, the project's `negotiation_round` increments and its `phase` returns to `APPROVALS_OPEN`, every other `APPROVED` consent record is reset to `PENDING` with the new `round_recorded`, and every crew window of the project still in `SCHEDULED` is set to `REVOKED`. The same veto landing on a project already in `DEENERGIZED` does all of that **and** compensates the money: the whole of `credit_reserved_cents` is moved into `credit_released_cents`, `credit_reserved_cents` becomes zero, and `credit_authorized_cents` is left unchanged. Physically nothing unwinds — the circuits stay `ISOLATED` — only the money and the schedule do.

### 3.3. Crew Windows, Mobilization Buffers and Weather

Crew time is booked as **WorkWindow** rows. A coordinator schedules one by supplying the `project_id`, the `party_id` of the crew resource occupying the interval, the `trade` — one of `ROOFING`, `SOLAR_REMOVAL` or `SOLAR_REINSTALL` — and the half-open interval `start_utc` (inclusive) and `end_utc` (exclusive), optionally with a forecast `weather_risk_score` between 0 and 100 inclusive that defaults to 0. The `party_id` must reference a party whose `party_type` is `ROOFER` or `SOLAR_CONTRACTOR`; anything else is `ERR_PARTY_TYPE_MISMATCH`. `end_utc` must be strictly after `start_utc`, and a violation is `ERR_INVALID_WINDOW_BOUNDS` (HTTP 422). Scheduling is also blocked while the project's posture is `FROZEN`. A new window is created in `SCHEDULED` with `supersedes_window_id` absent and both `actual_start_utc` and `actual_end_utc` absent.

Crew conflict detection uses the occupying party's own mobilization buffer, applied symmetrically on both sides. Take the candidate window's party and read that party's `mobilization_buffer_minutes`, converted to seconds; call it the buffer. The candidate conflicts with an existing window when the candidate's `start_utc` is strictly earlier than the existing window's `end_utc` plus the buffer, **and** the existing window's `start_utc` is strictly earlier than the candidate's `end_utc` plus the buffer. The candidate is refused with `ERR_CREW_WINDOW_CONFLICT` (HTTP 409) when at least one such conflicting window exists on the same `party_id`, is not the candidate itself, and has `status` of either `SCHEDULED` or `IN_PROGRESS`. Windows in `COMPLETED`, `WEATHER_ABORTED`, `SUPERSEDED` or `REVOKED` are excluded from the check — those states release the party's interval — and windows belonging to a different party never conflict. Comparisons are at second resolution and both are strict, which pins two consequences deliberately: whenever the buffer is greater than zero, exact adjacency (a candidate starting precisely at an existing window's `end_utc`) **is** a conflict, and the earliest legal start is the existing window's `end_utc` plus the buffer, which is itself accepted.

A window is advanced by supplying an `action` of `START`, `COMPLETE` or `WEATHER_ABORT`, optionally with an `abort_reason` and a revised `weather_risk_score`. `START` moves a `SCHEDULED` window to `IN_PROGRESS` and stamps `actual_start_utc` with the current instant; it requires the project not to be frozen and requires the current instant to be at or after the window's `start_utc`. `COMPLETE` moves an `IN_PROGRESS` window to `COMPLETED`, stamps `actual_end_utc`, and releases the crew interval for overlap purposes.

`WEATHER_ABORT` is accepted from either `SCHEDULED` or `IN_PROGRESS` and requires a non-empty `abort_reason`. It sets `status` to `WEATHER_ABORTED`, stamps `actual_end_utc`, records the reason, and increments the project's `weather_abort_count` by one. Because that counter feeds the posture rule of §2.6, the second abort on a project is the one that bites: two aborts already drive the project to `RESTRICTED`, and posture is recomputed at the end of the abort.

A weather-aborted window can be replaced. Rescheduling supplies a fresh `start_utc` and `end_utc`, optionally a different `party_id` and a revised `weather_risk_score`. The original window must be in `WEATHER_ABORTED`, and the replacement interval must pass the same interval-bounds and crew-overlap rules described above, with the same two error codes. On success the aborted window's `status` becomes `SUPERSEDED` and a brand-new window row is created in `SCHEDULED` with its `supersedes_window_id` pointing at the aborted window. The aborted window's contribution to `weather_abort_count` is not undone by rescheduling.

Windows can also be taken away without anyone asking. A `SYSTEM_OWNER` veto that withdraws authorization revokes every `SCHEDULED` window of the project, and an AHJ permit rejection revokes every `SCHEDULED` window of the project whose `start_utc` is at or after the current instant. In both cases `status` becomes `REVOKED` and the crew interval is released. `COMPLETED`, `SUPERSEDED` and `REVOKED` are all terminal for a window.

### 3.4. De-energizing the Array

The physical work cannot begin until the array is dead. Each string on the one-line diagram is registered as an **ArrayCircuit** by the coordinator, carrying a `circuit_label` unique within the project (a repeat is `ERR_DUPLICATE_CIRCUIT_LABEL`, HTTP 409), a `module_count` of at least 1 recording how many modules were originally on the circuit, and a `dc_kw` capacity strictly greater than zero. A new circuit starts with `status` `ENERGIZED`, `interlock_verified` false, and `isolated_at` and `reenergized_at` both absent.

The solar crew drives energization by supplying an `action` of `DE_ENERGIZE` or `RE_ENERGIZE`, an `interlock_verified` boolean, and optionally an `isolation_note` field note. This endpoint is refused while the project's posture is `FROZEN`.

`DE_ENERGIZE` forks on the interlock. From `ENERGIZED`, when the project's `phase` is `AUTHORIZED` and `interlock_verified` is submitted as true, the circuit moves `ENERGIZED → ISOLATED`, its `interlock_verified` is recorded as true, and `isolated_at` is stamped with the current instant. From the same `ENERGIZED` state under the same phase precondition but with `interlock_verified` submitted as false, the circuit instead moves `ENERGIZED → ISOLATION_PENDING` and records `interlock_verified` as false — a de-energize was recorded, but without a verified lockout/tagout interlock. That branch produces no project-level consequence at all, precisely because the circuit is not yet `ISOLATED`. A circuit sitting in `ISOLATION_PENDING` is finished off by a second de-energize carrying `interlock_verified` true, which moves `ISOLATION_PENDING → ISOLATED`, records the verified interlock, and stamps `isolated_at`.

Every de-energize that actually lands a circuit in `ISOLATED` — from either origin state — then asks whether the project can advance `AUTHORIZED → DEENERGIZED`. That advance requires the project's `phase` to be `AUTHORIZED`, the count of the project's circuits whose `status` is not `ISOLATED` to be zero, and the project to have at least one circuit at all. When it fires, the project stamps `deenergized_at` with the current instant, moves to `DEENERGIZED`, computes and reserves the provisional downtime credit as described in §3.9, and recomputes its posture.

### 3.5. Removal, Labeled Storage and Condition Grading

Each module and module-level optimizer is tracked as a **HardwareUnit**, and a unit carries **two independent state dimensions** that evolve on different endpoints and never imply one another. `handling_status` is the physical-handling dimension and takes `ON_ROOF`, `REMOVED`, `STORED`, `REINSTALLED` or `SCRAPPED`. `condition_grade` is the condition dimension and takes `UNINSPECTED`, `SERVICEABLE`, `DAMAGED` or `REPLACED`. A newly registered unit is `ON_ROOF` and `UNINSPECTED`.

The solar crew registers a unit by naming its `array_circuit_id` — which must belong to the same project — its `unit_type` (`PANEL` or `OPTIMIZER`), the `manufacturer` and `model_code` of record, a `serial_number` unique within the project, and its nameplate `rated_watts` (at least 1; the STC output for a panel, the maximum input watts for an optimizer). A duplicate serial within the project is `ERR_DUPLICATE_SERIAL` (HTTP 409). Registration recomputes `registered_unit_count`. A unit's `storage_bin_id`, `storage_label`, `warranty_variant`, `warranty_preserved`, `off_roof_days`, `removed_at`, `stored_at` and `reinstalled_at` are all absent at registration, and `warranty_risk_points` is zero.

**Storage bins** are created by the coordinator with a `bin_label` unique within the project (a repeat is `ERR_DUPLICATE_BIN_LABEL`, HTTP 409), a `capacity_slots` count of at least 1, a `climate_controlled` flag defaulting to false, and an `accepts_unit_types` list which must be a non-empty subset of `PANEL` and `OPTIMIZER` and which defaults to accepting both. A bin's `occupied_slots` starts at zero and is thereafter always the count of hardware units whose `storage_bin_id` is that bin **and** whose `handling_status` is exactly `STORED`.

Removal moves a unit `ON_ROOF → REMOVED` and stamps `removed_at`. It requires the unit to be `ON_ROOF`, its circuit's `status` to be `ISOLATED` — otherwise `ERR_CIRCUIT_NOT_ISOLATED` (HTTP 409) — and the project not to be frozen. Removal also **pins the warranty rule set** that will judge this unit later: `warranty_variant` becomes `MANUFACTURER_STRICT` when the project's `warranty_notice_status` is `FILED` at that instant, and `INSTALLER_LENIENT` otherwise. Nothing about `condition_grade` changes; the condition dimension is untouched by removal.

Storing a removed unit takes a `storage_bin_id` and an optional `storage_position`. The unit must be `REMOVED` and the project must not be frozen. The target bin must belong to the same project as the unit — otherwise `ERR_CROSS_PROJECT_REFERENCE` — the unit's `unit_type` must appear in the bin's `accepts_unit_types`, otherwise `ERR_BIN_UNIT_TYPE_REJECTED` (HTTP 422), and the bin's `occupied_slots` must be strictly less than its `capacity_slots`, otherwise `ERR_BIN_CAPACITY_EXCEEDED` (HTTP 409). A bin sitting at exactly capacity refuses the unit. On success the unit's `storage_bin_id` is written, `storage_position` is either the supplied value or the bin's `occupied_slots` plus one at that moment, and `storage_label` is composed as the bin's `bin_label` followed by a hyphen and the `storage_position`. `handling_status` becomes `STORED`, `stored_at` is stamped, the target bin's `occupied_slots` is recomputed, and the project's `stored_unit_count` is recomputed.

Condition grading is the other dimension, and it takes a `condition_grade` of `SERVICEABLE` or `DAMAGED`, a `disposition`, and an optional `damage_note`. The unit's `handling_status` must be `REMOVED` or `STORED`. Grading a unit `SERVICEABLE` moves the condition dimension `UNINSPECTED → SERVICEABLE` and leaves `handling_status` completely alone. Grading a unit `DAMAGED` with a `disposition` of `RETAIN` moves the condition dimension to `DAMAGED` from either `UNINSPECTED` or `SERVICEABLE`, records the `damage_note`, and again leaves `handling_status` alone — the unit stays available for replacement sourcing. Grading a unit `DAMAGED` with a `disposition` of `SCRAP` is the one action that writes both dimensions at once: `condition_grade` becomes `DAMAGED` and `handling_status` becomes `SCRAPPED`, from either `REMOVED` or `STORED`. Scrapping a unit that was `STORED` also recomputes the `occupied_slots` of its bin, since the slot is now free, whereas scrapping a unit that was merely `REMOVED` touches no bin. Every grading recomputes `damaged_unit_count`, and grading that reaches `SCRAPPED` also recomputes `scrapped_unit_count` and, where the unit was stored, `stored_unit_count`. `SCRAPPED` is terminal on the handling dimension.

Both storage and condition grading then ask whether the project can advance `DEENERGIZED → DECK_WORK`. That advance requires the project's `phase` to be `DEENERGIZED`, `registered_unit_count` to be at least 1, and the count of the project's units whose `handling_status` is neither `STORED` nor `SCRAPPED` to be zero — in other words, every registered unit is either safely in a bin or written off. When it fires, the project moves to `DECK_WORK` and recomputes `stored_unit_count`, `scrapped_unit_count` and posture.

### 3.6. Deck Findings, Upgrade Scoping and the Re-Permitting Cascade

With the array off, the roofer finally sees the deck. Each problem is recorded as a **DeckFinding** with a `finding_type` — one of `SHEATHING_ROT`, `FASTENER_PULLOUT`, `FLASHING_FAILURE`, `MOISTURE_INTRUSION` or `STRUCTURAL_DEFLECTION` — a `severity` of `LOW`, `MEDIUM`, `HIGH` or `CRITICAL`, an `affected_area_sqft` strictly greater than zero, and an `attachment_count_affected` of zero or more mounting attachments or flashings. A new finding is `OPEN` with `upgrade_cost_cents` zero, `scoped_by_party_id`, `completed_by_party_id`, `waiver_reason`, `scoped_at` and `completed_at` all absent. One derived flag is computed at creation and never changes: `requires_repermit` is true exactly when the `severity` is `HIGH` or `CRITICAL` **and** the `finding_type` is `SHEATHING_ROT` or `STRUCTURAL_DEFLECTION`. Recording a finding recomputes `open_critical_finding_count` and posture — which is how a single `CRITICAL` finding freezes the whole project the moment it is written down.

A finding is then driven by an `action` of `SCOPE`, `COMPLETE`, `WAIVE` or `RESCOPE`, with an optional `waiver_reason`. Every one of these requires the acting party's `party_type` to be `ROOFER`; anything else is `ERR_PARTY_TYPE_MISMATCH`.

**Scoping** takes an `OPEN` finding to `UPGRADE_SCOPED` and prices the work. The price of a scoped upgrade is assembled in four steps.

First, the deck area is priced on marginal tiers. The first 100 square feet of `affected_area_sqft` cost 950 cents each. The portion above 100 and up to 300 square feet costs 780 cents each. Anything above 300 square feet costs 640 cents each. Each tier contributes only the area that actually falls inside it, so a 250-square-foot finding pays the first tier on 100 square feet and the second tier on 150.

Second, the attachments are priced. Each affected attachment or flashing costs 4,200 cents, and that whole attachment subtotal is multiplied by 1.25 when the `finding_type` is `FLASHING_FAILURE`, and by 1.00 for every other finding type.

Third, the severity multiplier is applied to the sum of the area subtotal and the attachment subtotal. The published multipliers are 1.00 for `LOW`, 1.15 for `MEDIUM`, 1.40 for `HIGH` and 1.75 for `CRITICAL`. When the project's `posture` is `FROZEN` at the instant of scoping, an emergency bump of 0.25 is **added to the multiplier** before it is used, so the same finding costs strictly more when it is scoped on a frozen project than on an `OPEN` or `RESTRICTED` one. Call the product of the two subtotals and the (possibly bumped) multiplier the raw amount.

Fourth, a cap and a floor are applied as a nest, and the nesting order matters. The raw amount is rounded half up to whole cents and then capped at 2,500,000 cents. Separately, the attachment subtotal is rounded half up to whole cents and compared against a base floor of 50,000 cents, and the larger of those two becomes the effective floor. The finding's `upgrade_cost_cents` is the larger of the capped figure and the effective floor. The interaction is deliberate: when the attachment subtotal alone exceeds the cap, the floor wins and the result legitimately exceeds 2,500,000 cents.

Scoping is gated on the project's budget. The project's `scoped_upgrade_cost_cents` — the sum of `upgrade_cost_cents` over the project's findings whose `status` is `UPGRADE_SCOPED` or `UPGRADE_COMPLETED` — plus the newly computed cost for this finding must not exceed `upgrade_budget_cents`; when it would, the scope is refused with `ERR_UPGRADE_BUDGET_EXCEEDED` (HTTP 402). No sibling finding enters the price formula itself; siblings only enter through this budget gate.

On success the finding's `upgrade_cost_cents` is written, `status` becomes `UPGRADE_SCOPED`, `scoped_at` is stamped with the current instant, and `scoped_by_party_id` records the acting `X-User-ID`. The project's `scoped_upgrade_cost_cents` and `open_critical_finding_count` are recomputed.

Then the cascade. When the finding's `requires_repermit` is true **and** the project has a permit application in `APPROVED` **and** that permit's jurisdiction has `repermit_required_for_reinstall` set to true, that permit reverts `APPROVED → SUBMITTED`: its `revision_count` increases by one, its `reopened_by_finding_id` is set to this finding's identifier, its `submitted_at` is stamped with the current instant, its `fee_cents` is recomputed by the permit fee rule of §3.7, and its `review_deadline_utc` is recomputed as the new `submitted_at` plus the jurisdiction's `permit_review_days` whole days. Because that permit left `APPROVED`, every inspection under it whose `status` is `PASSED` and whose `inspection_type` is `ROOF_DECK` or `MOUNTING` is invalidated to `CORRECTION_REQUIRED` with its `attempt_number` increased by one. Passed electrical-final inspections are **not** invalidated by this cascade. Finally posture is recomputed, and the now-`SUBMITTED` re-permit under a re-permit-requiring jurisdiction is exactly what drives the project to `RESTRICTED`. That is four levels in one request: finding, permit, inspection, posture.

**Waiving** is the sibling branch out of `OPEN`, and it behaves differently in every respect. It requires a non-empty `waiver_reason` justifying closing the finding without work. It sets `status` to `WAIVED`, stamps `completed_at`, and leaves `upgrade_cost_cents` at zero — so a waived finding contributes nothing to `scoped_upgrade_cost_cents`, consumes no budget, and reopens no permit. It carries a consequence the scope branch does not: when the waived finding's `severity` is `CRITICAL`, the project's `warranty_notice_status` is set to `LAPSED`, because the manufacturer was told the deck would be remediated and it will not be. Waiving recomputes `open_critical_finding_count` and posture — which is how waiving the last `CRITICAL` finding thaws a frozen project — and then evaluates the `DECK_WORK → REINSTALL` advance. `WAIVED` is terminal for a finding.

**Completing** takes a finding from `UPGRADE_SCOPED` to `UPGRADE_COMPLETED`, stamps `completed_at`, and records the acting `X-User-ID` as `completed_by_party_id`. Segregation of duties is absolute here: the acting `X-User-ID` must differ from the finding's `scoped_by_party_id`, and a roofer attempting to sign off its own scope is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Completion recomputes posture and evaluates the `DECK_WORK → REINSTALL` advance.

**Rescoping** is the revert edge, taking a finding from `UPGRADE_SCOPED` back to `OPEN`. It resets `upgrade_cost_cents` to zero and clears both `scoped_by_party_id` and `scoped_at`, then recomputes `scoped_upgrade_cost_cents`, `open_critical_finding_count` and posture. One asymmetry is intentional and must not be smoothed over: rescoping does **not** re-approve a permit application that the original scoping reopened. The permit stays `SUBMITTED` and must be decided again by the authority.

The project leaves deck work when the roof is settled. The `DECK_WORK → REINSTALL` advance is evaluated at the end of every finding upgrade action and at the end of every AHJ permit decision. It requires the project's `phase` to be `DECK_WORK`, the count of the project's findings whose `status` is neither `UPGRADE_COMPLETED` nor `WAIVED` to be zero, and one further condition: either the project has no finding at all whose `requires_repermit` is true and whose `status` is `UPGRADE_COMPLETED`, or the project has at least one permit application in `APPROVED`. When it fires, the project moves to `REINSTALL` and recomputes posture.

### 3.7. Permits, Fees and AHJ Inspections

A **PermitApplication** is drafted by the coordinator against a `project_id` and a `jurisdiction_id`, with a `scope` of `REINSTALL_ONLY`, `STRUCTURAL_UPGRADE` or `FULL_REPERMIT` and an `expedited` flag defaulting to false. A new application is `DRAFT` with `revision_count` zero, `fee_cents` zero, and `submitted_at`, `decided_at`, `review_deadline_utc`, `rejection_reason` and `reopened_by_finding_id` all absent. Drafting recomputes the project's posture — a `DRAFT` application under a re-permit-requiring jurisdiction already restricts the project.

Submission is accepted from `DRAFT` and, closing the resubmission cycle, from `REJECTED`. Either way `status` becomes `SUBMITTED`, `submitted_at` is stamped with the current instant, and `review_deadline_utc` is set to that `submitted_at` plus the jurisdiction's `permit_review_days` whole days. A resubmission out of `REJECTED` additionally increases `revision_count` by one and clears any recorded `rejection_reason`. Every submission recomputes `fee_cents` from scratch.

The fee is the sum of four terms. The scope base is 18,000 cents for `REINSTALL_ONLY`, 46,000 cents for `STRUCTURAL_UPGRADE` and 72,000 cents for `FULL_REPERMIT`. To that is added the project's `system_dc_kw` multiplied by 850 cents per kilowatt, rounded half up to whole cents — this per-kilowatt term is the only term that is rounded. To that is added the jurisdiction's `expedite_fee_cents` when the application's `expedited` flag is true, and nothing when it is false. To that is added 9,000 cents for each revision, counted using the value of `revision_count` **after** the increment performed by this very submission — so a first submission, whose `revision_count` is still zero, adds nothing, while the first resubmission adds 9,000 cents. The re-permit reopening cascade of §3.6 also increments `revision_count` and recomputes the fee, and it counts the same way.

An `AHJInspector` for the governing jurisdiction then decides a `SUBMITTED` application, supplying a `decision` of `APPROVE` or `REJECT` and, on a rejection, a `rejection_reason`. The two branches diverge sharply. `APPROVE` sets `status` to `APPROVED`, stamps `decided_at`, recomputes posture, and evaluates the `DECK_WORK → REINSTALL` advance; it has no posture consequence of its own beyond clearing the `SUBMITTED` restriction. `REJECT` sets `status` to `REJECTED`, stamps `decided_at`, records the `rejection_reason`, and drives the project's `posture` to `FROZEN`; because the project froze, every crew window of the project still in `SCHEDULED` whose `start_utc` is at or after the current instant is set to `REVOKED`.

**Inspections** are booked by the coordinator against a permit application, which becomes the booking's `permit_application_id` and is its only route to a project — an inspection reaches its project through its parent application, never directly. The booking names an `inspection_type` of `ROOF_DECK`, `MOUNTING` or `ELECTRICAL_FINAL`, a `slot_date` as a UTC calendar date in year-month-day form, and an inclusive inspector arrival window given by `window_start_utc` and `window_end_utc`. The parent application's `status` must be `SUBMITTED` or `APPROVED`; anything else is `ERR_PERMIT_NOT_SUBMITTED` (HTTP 409). The window must be well formed: `window_end_utc` strictly after `window_start_utc`, both instants on the same UTC calendar date, and `slot_date` exactly equal to the UTC date of `window_start_utc`. A violation of any of those three is `ERR_INVALID_WINDOW_BOUNDS`.

Two availability rules then apply, in this order. The backlog floor comes first: the earliest bookable instant is the current instant plus the jurisdiction's `backlog_days` whole days, and a `window_start_utc` strictly earlier than that floor is refused with `ERR_INSPECTION_BACKLOG_VIOLATION` (HTTP 422). A candidate starting exactly at the floor is accepted. Aggregate day capacity comes second, and it is scoped to the **jurisdiction**, not to the project: count every inspection booked under any permit application governed by the same jurisdiction whose `slot_date` equals the candidate's `slot_date` and whose `status` is `SCHEDULED` or `CORRECTION_REQUIRED`; when that count has already reached the jurisdiction's `inspection_slots_per_day`, the booking is refused with `ERR_INSPECTION_SLOT_FULL` (HTTP 409). Inspections in `PASSED` or `FAILED` have released their slot and are not counted. Window geometry never rejects a booking here — two inspections on the same `slot_date` whose windows merely touch at an endpoint are both legal while capacity remains, and only the aggregate count refuses. A new inspection is created `SCHEDULED` with `attempt_number` 1, `result_note` and `inspected_at` absent, consuming one aggregate slot on its `slot_date`, and the project's posture is recomputed.

The inspector records an outcome with a `result` of `PASS`, `FAIL` or `CORRECTION` and an optional `result_note`, always from `SCHEDULED`, and always stamping `inspected_at` with the current instant. `PASS` additionally requires the parent application's `status` to still be `SUBMITTED` or `APPROVED`; it sets `status` to `PASSED`, releases the jurisdiction's slot for that `slot_date`, and, when the inspection's `inspection_type` is `ELECTRICAL_FINAL`, evaluates the project's `REINSTALL → COMMISSIONED` advance. `FAIL` sets `status` to `FAILED`, likewise releases the slot, and recomputes posture with the failed inspection counting as an open compliance defect, which restricts the project. `CORRECTION` sets `status` to `CORRECTION_REQUIRED` and — unlike the other two — **keeps the slot consumed**, so it continues to count against `inspection_slots_per_day`; a correction-required inspection also restricts the project through the posture rule. The fourth way into `CORRECTION_REQUIRED` is not an inspector action at all: it is the system cascade of §3.6, which invalidates a `PASSED` deck or mounting inspection when its parent application leaves `APPROVED` in the same request, incrementing `attempt_number`.

### 3.8. Sourcing Replacements under Mismatched-Model Rules

Some units come off the roof broken, and getting an identical part is not always possible. A **SourcingOrder** is raised by the coordinator against a `project_id` and the `hardware_unit_id` of the damaged unit, recording the `requested_model_code` originally asked for alongside what the distributor can actually supply: `offered_manufacturer`, `offered_model_code`, `offered_rated_watts` (at least 1) and `unit_cost_cents` (never negative). An optional `waiver_ref` carries an engineering mismatch-waiver reference. The order must carry `expected_project_version` per §2.9. The target unit's `condition_grade` must be `DAMAGED` and its `handling_status` must be `REMOVED` or `STORED`.

Classification runs in a pinned five-step order, and the pinning matters because the last step writes a field the earlier steps read.

Step one computes `watt_delta_pct` as the offered watts minus the unit's `rated_watts` of record, divided by that same `rated_watts` of record, multiplied by 100, rounded half up to two decimal places. It is signed: an offered part with fewer watts yields a negative delta.

Step two computes `tolerance_pct` from a snapshot of the project taken **before** step five mutates it. The base tolerance is 3.00 percent. When the snapshot of the project's `warranty_notice_status` is `FILED`, a further 1.00 percent is added, because a notified manufacturer tolerates more variation. When the order carries a non-null `waiver_ref`, a further 2.00 percent is added. Both bonuses can apply at once. The resulting figure is recorded on the order as the tolerance actually applied.

Step three assigns `match_class`. It is `EXACT` when the `offered_manufacturer` equals the unit's `manufacturer` of record and the `offered_model_code` equals the unit's `model_code` of record. Otherwise it is `COMPATIBLE` when the `offered_manufacturer` still equals the unit's `manufacturer` of record and the absolute value of `watt_delta_pct` is less than or equal to `tolerance_pct` — a delta exactly equal to the tolerance is `COMPATIBLE`. In every other case it is `MISMATCHED`. The consequence of the tolerance bonus is that the same part can be `MISMATCHED` on an un-notified project and `COMPATIBLE` on a notified one.

Step four assigns the order's initial `status`. An `EXACT` match is `APPROVED` outright. A `COMPATIBLE` match on a `HOST_OWNED` project is also `APPROVED` outright, since the host owns the hardware and needs no third party's blessing. A `COMPATIBLE` match on a `LEASE` or `PPA` project lands in `PENDING_REVIEW`, awaiting the system owner. A `MISMATCHED` part with a non-null `waiver_ref` also lands in `PENDING_REVIEW`. A `MISMATCHED` part with no `waiver_ref` is refused outright with `ERR_MODEL_MISMATCH_NOT_WAIVED` (HTTP 422) and **no order row is persisted**.

Step five, strictly after the four above, is the mutation. When the resulting `match_class` is anything other than `EXACT` and the project's `warranty_notice_status` is `FILED`, that status is reset to `PENDING`, because the manufacturer must be re-notified that the model of record changed. Every persisted sourcing order also increments the project's `version` by one — which is precisely why a client that raised one order and then raises a second without re-reading the project trips the stale-version rule of §2.9.

A `PENDING_REVIEW` order is decided by the `SystemOwner` whose party identifier matches the project's `system_owner_party_id`, supplying a `decision` of `APPROVE` or `REJECT` and an optional `review_note`. `APPROVE` moves the order to `APPROVED`. `REJECT` moves it to `REJECTED` and leaves the target unit's `condition_grade` at `DAMAGED` — the unit is still broken and still blocks its circuit. Both `REJECTED` and `RECEIVED` are terminal for an order.

Receipt closes the loop. The coordinator receives an `APPROVED` order by supplying the `received_serial_number` of the part that actually arrived, which must be unique within the project — a collision is `ERR_DUPLICATE_SERIAL`. Before anything is written, the resulting circuit watt spread is checked. Take the circuit of the target unit, and collect the `rated_watts` of every hardware unit on that circuit whose `unit_type` matches the target's and whose `handling_status` is not `SCRAPPED`, evaluated as if the receipt had already written `offered_rated_watts` onto the target unit. The spread is the largest of those wattages minus the smallest, divided by the smallest, multiplied by 100, rounded half up to two decimal places. When that spread is strictly greater than 3.00 percent the receipt is refused with `ERR_CIRCUIT_WATT_SPREAD_EXCEEDED` (HTTP 422); a spread exactly equal to 3.00 percent is accepted. Panels and optimizers are evaluated as independent populations — an optimizer replacement never conflicts with the panel spread on the same circuit.

On success the order's `status` becomes `RECEIVED` and `received_at` is stamped with the current instant. The target unit's condition dimension moves `DAMAGED → REPLACED`, and its `manufacturer`, `model_code`, `rated_watts` and `serial_number` are all overwritten from the order's offered values and received serial. The project's `damaged_unit_count` is recomputed. The unit's `handling_status` is untouched by receipt — a stored unit stays stored.

### 3.9. Reinstall, Warranty Preservation, Commissioning and Settlement

Module warranties do not automatically survive a remove-and-reinstall; the manufacturer has to be told. A project's `warranty_notice_status` is `NOT_REQUIRED` on a `HOST_OWNED` system and `PENDING` on a `LEASE` or `PPA` system, and the coordinator moves it to `FILED` by filing the notice, supplying the `manufacturer` being notified, the manufacturer case `notice_reference`, and `expected_project_version`. Filing sets `warranty_notice_status` to `FILED`, stamps `warranty_notice_filed_at` with the current instant, records the case reference as `warranty_notice_reference`, increments the project's `version`, and recomputes posture. The status can slide backwards in two ways already described: a non-exact sourcing order resets a `FILED` status to `PENDING`, and waiving a `CRITICAL` deck finding sets it to `LAPSED`.

Reinstalling a unit moves it `STORED → REINSTALLED` and stamps `reinstalled_at`. The preconditions are the strictest in the system: the unit must be `STORED`, its `condition_grade` must be `SERVICEABLE` or `REPLACED` (otherwise `ERR_UNIT_NOT_SERVICEABLE`, HTTP 409), the project's `phase` must be `REINSTALL`, the project's `posture` must be exactly `OPEN`, the unit's circuit must still be `ISOLATED`, and either the project's `ownership_model` is `HOST_OWNED` or its `warranty_notice_status` is `FILED` — a reinstall on a leased or power-purchase project without a filed notice is refused with `ERR_WARRANTY_NOTICE_MISSING` (HTTP 409).

Reinstall computes the unit's `off_roof_days` as the calendar date of `reinstalled_at` minus the calendar date of `removed_at`, in whole UTC days, and then judges warranty preservation under the variant pinned at removal.

Under `MANUFACTURER_STRICT`, the unit's `warranty_preserved` is true only when all three of the following hold: `off_roof_days` is at most 30; either `off_roof_days` is at most 14 or the unit's storage bin was `climate_controlled`; and the unit's `condition_grade` is `SERVICEABLE` or `REPLACED`. In other words the strict variant tolerates a full month off the roof provided any storage beyond a fortnight was climate controlled, and it accepts a unit whose damaged part was replaced.

Under `INSTALLER_LENIENT`, the unit's `warranty_preserved` is true only when `off_roof_days` is at most 14 **and** the unit's `condition_grade` is exactly `SERVICEABLE`. There is no climate-control escape hatch and a `REPLACED` unit does not qualify. The two variants therefore return opposite verdicts on identical inputs — a `REPLACED` unit stored 20 days in a climate-controlled bin is preserved under the strict variant and not preserved under the lenient one.

When `warranty_preserved` comes out true, the unit's `warranty_risk_points` is 0. When it comes out false, `warranty_risk_points` is 10 under `MANUFACTURER_STRICT` and 25 under `INSTALLER_LENIENT` — the lenient variant carries the heavier penalty precisely because no notice was on file. Reinstall also recomputes the `occupied_slots` of the unit's storage bin, since the slot is freed, while `storage_bin_id` and `storage_label` are deliberately **retained** as provenance rather than cleared. The project's `stored_unit_count`, `reinstalled_unit_count` and roll-up `warranty_preserved` are recomputed; the project-level flag is the logical AND of `warranty_preserved` across every unit of the project whose `handling_status` is `REINSTALLED`, taken in `created_at` ascending order, and it is true when that set is empty.

Re-energization closes the physical cycle, moving a circuit `ISOLATED → ENERGIZED` and stamping the circuit's `reenergized_at`. It requires the circuit to be `ISOLATED`, the project's `phase` to be `REINSTALL`, the project's `posture` to be exactly `OPEN`, and every hardware unit on that circuit whose `handling_status` is not `SCRAPPED` to be `REINSTALLED`; a circuit still carrying a non-scrapped unit that is not reinstalled is refused with `ERR_CIRCUIT_UNITS_NOT_REINSTALLED` (HTTP 409).

Each re-energization then evaluates the project's `REINSTALL → COMMISSIONED` advance, as does each passed electrical-final inspection. That advance requires the project's `phase` to be `REINSTALL`, the count of the project's circuits whose `status` is not `ENERGIZED` to be zero, and the re-inspection gate to be satisfied. The gate is satisfied in any of three ways: the project has no permit application at all; the jurisdiction governing its permit applications has `reinspection_required` set to false; or there exists an inspection under one of the project's `APPROVED` permit applications whose `inspection_type` is `ELECTRICAL_FINAL` and whose `status` is `PASSED`. When the advance fires, the project stamps its own `reenergized_at` with the current instant, moves to `COMMISSIONED`, and recomputes `downtime_days_actual`, the roll-up `warranty_preserved` and posture. `downtime_days_actual` is the count of distinct UTC calendar dates in the inclusive range from the date of the project's `deenergized_at` to the date of its `reenergized_at`, and it is zero while either endpoint is absent.

That leaves the money, and there are two different answers to "what is the downtime worth", computed at two different moments from two different input sets.

Every credit starts from the same two ingredients: the array's `baseline_daily_kwh` and a rate of 14 cents per kilowatt-hour of lost production. An ownership factor then scales the result according to who was actually deprived of the energy: 0.00 for `HOST_OWNED` (the host owns the array, so no credit is owed at all), 1.00 for `LEASE`, and 0.85 for `PPA`.

The **provisional, forward-looking** credit is reserved at the moment the project advances `AUTHORIZED → DEENERGIZED`. It is the `baseline_daily_kwh` multiplied by `downtime_days_estimated`, multiplied by 14 cents, multiplied by the ownership factor, with a **single** rounding half up to whole cents applied to that entire product at the end. It reads nothing but those three project fields; no crew window, no circuit and no unit enters it, which is exactly why it is insensitive to what actually happens. The result is written to `provisional_credit_cents`, and the same amount is added to both `credit_authorized_cents` and `credit_reserved_cents`.

The **final, chronological** credit is computed when the coordinator settles a `COMMISSIONED` project, optionally recording a `settlement_note`. It replays the downtime day by day. Build the ordered list of distinct UTC calendar dates in the inclusive range from the date of `deenergized_at` to the date of `reenergized_at`, ascending by date. For each date in turn, determine a day factor: it is 0.5 when there exists a work window on this project whose `status` is `WEATHER_ABORTED` and whose interval covers that date — meaning the date of the window's `start_utc` is at or before the date in question and the date in question is at or before the date of the window's `end_utc` — and 1.0 otherwise. Only windows in `WEATHER_ABORTED` count for this; `SUPERSEDED`, `REVOKED`, `COMPLETED`, `SCHEDULED` and `IN_PROGRESS` windows are all excluded, which means a rescheduled abort stops halving its days once it becomes `SUPERSEDED`. That day's cents are the `baseline_daily_kwh` multiplied by 14 cents, multiplied by the ownership factor, multiplied by that day's factor, **rounded half up to whole cents for that day**. The final figure is the sum of those per-day whole-cent amounts. The rounding order is pinned: rounding once per calendar day *before* summing is correct, and summing the unrounded day amounts and rounding once at the end is wrong. Because of that, and because of the weather halving, identical inputs give a different total from the provisional variant.

Settlement itself is guarded and then transacts. The project's `phase` must be `COMMISSIONED`; a settlement requested on any other phase is refused with `ERR_SETTLEMENT_NOT_READY` (HTTP 409). The credit ledger identity of §2.7 must hold before anything is applied, and a project whose accounts do not balance is refused with `ERR_CREDIT_LEDGER_UNBALANCED`. On success the computed figure is written to `final_credit_cents`; the difference between `final_credit_cents` and `credit_reserved_cents` is taken, and when that difference is positive it is added to `credit_authorized_cents` (a negative or zero difference leaves the authorized total alone); `credit_settled_cents` is set to `final_credit_cents`; `credit_reserved_cents` is set to zero; `credit_released_cents` is set to `credit_authorized_cents` minus `credit_settled_cents`; and the project's `phase` moves `COMMISSIONED → CLOSED`. `CLOSED` is terminal for a project.

## 4. Endpoint Definitions

Endpoints that bring a new, distinct resource into existence — a party, a jurisdiction, a project, a consent request, a circuit, a bin, a hardware unit, a deck finding, a permit application, an inspection booking, a crew window, a rescheduled replacement window, or a sourcing order — answer `201 Created`. Endpoints that modify an existing resource, including every action endpoint that drives a state machine, and every read, answer `200 OK`. Errors carry the HTTP status listed in §5.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/reroof/parties` | Register a coordination party (roofer, solar owner, third-party system owner, or SunSystem solar contractor crew). | ProjectCoordinator |
| GET | `/reroof/parties` | List parties, optionally filtered by `party_type`. | ProjectCoordinator, SolarContractor, RoofingContractor, SolarOwner, SystemOwner, AHJInspector |
| GET | `/reroof/parties/{id}` | Read one party including its mobilization buffer and crew capacity. | ProjectCoordinator, SolarContractor, RoofingContractor, SolarOwner, SystemOwner, AHJInspector |
| POST | `/reroof/jurisdictions` | Register an authority having jurisdiction with its re-permit, re-inspection, slot-capacity and backlog policy. Immutable once created. | ProjectCoordinator |
| GET | `/reroof/jurisdictions` | List jurisdictions, optionally filtered by `code`. | ProjectCoordinator, AHJInspector |
| GET | `/reroof/jurisdictions/{id}` | Read one jurisdiction and its re-permit, re-inspection, slot-capacity and backlog policy. | ProjectCoordinator, SolarContractor, RoofingContractor, SolarOwner, SystemOwner, AHJInspector |
| POST | `/reroof/projects` | Open a remove-and-reinstall project for a roof replacement. | ProjectCoordinator |
| GET | `/reroof/projects` | List projects, filterable by any of the four party foreign keys, by `phase` and by `posture`. | ProjectCoordinator, SolarContractor, RoofingContractor, SolarOwner, SystemOwner |
| GET | `/reroof/projects/{id}` | Read one project including its derived posture, credit ledger, counters and current version. | ProjectCoordinator, SolarContractor, RoofingContractor, SolarOwner, SystemOwner, AHJInspector |
| GET | `/reroof/projects/{id}/downtime-summary` | Computed read of the downtime and credit position, including whether the credit ledger identity currently balances. | ProjectCoordinator, SolarOwner, SystemOwner |
| POST | `/reroof/projects/{id}/warranty-notice` | File (or re-file) the manufacturer notification that preserves module warranty across the remove-and-reinstall. | ProjectCoordinator |
| POST | `/reroof/projects/{id}/credit-settlement` | Settle the downtime credit on a COMMISSIONED project using the final chronological variant and close the project. | ProjectCoordinator |
| POST | `/reroof/projects/{id}/party-approvals` | Open a consent request for one of the three coordinating parties; the first one moves the project into APPROVALS_OPEN. | ProjectCoordinator |
| GET | `/reroof/party-approvals/{id}` | Read one consent record. | ProjectCoordinator, RoofingContractor, SolarOwner, SystemOwner |
| GET | `/reroof/party-approvals` | List consent records, filterable by project, party and status. | ProjectCoordinator, RoofingContractor, SolarOwner, SystemOwner |
| POST | `/reroof/party-approvals/{id}/decision` | Record a party's APPROVE or REQUEST_CHANGES decision for the current negotiation round. | RoofingContractor, SolarOwner, SystemOwner |
| POST | `/reroof/projects/{id}/array-circuits` | Register a PV string/circuit on the project. | ProjectCoordinator |
| GET | `/reroof/array-circuits/{id}` | Read one array circuit including its isolation status and interlock flag. | ProjectCoordinator, SolarContractor, RoofingContractor, SolarOwner, SystemOwner, AHJInspector |
| GET | `/reroof/projects/{id}/array-circuits` | List the circuits of a project. | ProjectCoordinator, SolarContractor, RoofingContractor, SolarOwner, SystemOwner |
| POST | `/reroof/array-circuits/{id}/energization` | De-energize or re-energize a circuit. DE_ENERGIZE without a verified interlock lands in ISOLATION_PENDING instead of ISOLATED. | SolarContractor |
| POST | `/reroof/projects/{id}/storage-bins` | Create a labeled storage bin for removed modules and optimizers. | ProjectCoordinator |
| GET | `/reroof/storage-bins/{id}` | Read one storage bin including its live `occupied_slots` figure. | ProjectCoordinator, SolarContractor, RoofingContractor, SolarOwner, SystemOwner |
| GET | `/reroof/projects/{id}/storage-bins` | List the storage bins of a project with their derived occupancy. | ProjectCoordinator, SolarContractor |
| POST | `/reroof/projects/{id}/hardware-units` | Register a module or optimizer that is currently on the roof. | SolarContractor |
| GET | `/reroof/hardware-units/{id}` | Read one hardware unit including both state dimensions, its storage label and its warranty verdict. | ProjectCoordinator, SolarContractor, RoofingContractor, SolarOwner, SystemOwner |
| GET | `/reroof/hardware-units` | List hardware units, filterable by project, circuit, storage bin and either state dimension. | ProjectCoordinator, SolarContractor, RoofingContractor, SolarOwner, SystemOwner |
| POST | `/reroof/hardware-units/{id}/removal` | Record physical removal of the unit from the roof; pins the warranty variant from the project's notice status at this instant. | SolarContractor |
| POST | `/reroof/hardware-units/{id}/storage` | Place a removed unit into a labeled storage bin slot. | SolarContractor |
| POST | `/reroof/hardware-units/{id}/condition-grade` | Grade a removed or stored unit SERVICEABLE or DAMAGED; a DAMAGED unit may be retained for replacement sourcing or scrapped outright. | SolarContractor |
| POST | `/reroof/hardware-units/{id}/reinstall` | Reinstall a stored, serviceable-or-replaced unit onto the new roof and evaluate its warranty preservation. | SolarContractor |
| POST | `/reroof/projects/{id}/deck-findings` | Record a roof deck condition finding discovered once the array came off. | RoofingContractor |
| GET | `/reroof/deck-findings/{id}` | Read one deck finding including its scoped cost and the two segregation-of-duties party references. | ProjectCoordinator, RoofingContractor, SolarOwner, SystemOwner, AHJInspector |
| GET | `/reroof/deck-findings` | List deck findings, filterable by project, severity, status and either segregation-of-duties party reference. | ProjectCoordinator, RoofingContractor, SolarOwner, SystemOwner, AHJInspector |
| POST | `/reroof/deck-findings/{id}/upgrade` | Drive the attachment/flashing upgrade branch of a finding: SCOPE prices it and may reopen an approved permit, COMPLETE signs it off under segregation of duties, WAIVE closes it without work, RESCOPE reverts to OPEN. | RoofingContractor |
| POST | `/reroof/permit-applications` | Draft a re-permit application for the reinstall with the authority having jurisdiction. | ProjectCoordinator |
| GET | `/reroof/permit-applications/{id}` | Read one permit application including its review deadline, fee and re-permit provenance. | ProjectCoordinator, RoofingContractor, SolarOwner, SystemOwner, AHJInspector |
| GET | `/reroof/permit-applications` | List permit applications, filterable by project, jurisdiction, status and the finding that reopened them. | ProjectCoordinator, RoofingContractor, SolarOwner, SystemOwner, AHJInspector |
| POST | `/reroof/permit-applications/{id}/submission` | Submit or re-submit the application to the AHJ; recomputes the fee and the review deadline. | ProjectCoordinator |
| POST | `/reroof/permit-applications/{id}/decision` | Record the AHJ decision. APPROVE clears the re-permit gate; REJECT freezes the project and revokes future crew windows. | AHJInspector |
| POST | `/reroof/permit-applications/{id}/inspections` | Book an AHJ inspection slot against the application, subject to the jurisdiction's backlog floor and per-day aggregate capacity. | ProjectCoordinator |
| GET | `/reroof/permit-applications/{id}/inspections` | List the inspections booked under one permit application. | ProjectCoordinator, RoofingContractor, SolarOwner, SystemOwner, AHJInspector |
| GET | `/reroof/inspections/{id}` | Read one inspection including its slot date, window, attempt number and result. | ProjectCoordinator, SolarContractor, RoofingContractor, SolarOwner, SystemOwner, AHJInspector |
| POST | `/reroof/inspections/{id}/result` | Record the inspector's PASS, FAIL or CORRECTION result. PASS and FAIL release the AHJ slot; CORRECTION keeps it consumed. | AHJInspector |
| POST | `/reroof/work-windows` | Schedule a crew window on a party's calendar, subject to that party's symmetric mobilization buffer. | ProjectCoordinator |
| GET | `/reroof/work-windows/{id}` | Read one crew window. | ProjectCoordinator, SolarContractor, RoofingContractor, SolarOwner, SystemOwner |
| GET | `/reroof/work-windows` | List crew windows, filterable by project, party, status and the aborted window they replace. | ProjectCoordinator, SolarContractor, RoofingContractor, SolarOwner, SystemOwner |
| POST | `/reroof/work-windows/{id}/status` | Advance a crew window: START, COMPLETE or WEATHER_ABORT. | ProjectCoordinator, RoofingContractor, SolarContractor |
| POST | `/reroof/work-windows/{id}/reschedule` | Replace a weather-aborted window with a new one, marking the original SUPERSEDED. | ProjectCoordinator |
| POST | `/reroof/sourcing-orders` | Source a replacement for a damaged module or optimizer; classifies the offered part EXACT, COMPATIBLE or MISMATCHED under the mismatched-model rules. | ProjectCoordinator |
| GET | `/reroof/sourcing-orders/{id}` | Read one sourcing order including its match classification and applied tolerance. | ProjectCoordinator, SolarContractor, SystemOwner, SolarOwner |
| GET | `/reroof/sourcing-orders` | List sourcing orders, filterable by project, target unit, status and match class. | ProjectCoordinator, SolarContractor, SystemOwner, SolarOwner |
| POST | `/reroof/sourcing-orders/{id}/review` | Third-party system owner decision on a sourcing order that needs review because the offered part is not an exact match. | SystemOwner |
| POST | `/reroof/sourcing-orders/{id}/receipt` | Receive the replacement part and write it onto the damaged unit, subject to the circuit watt-spread rule. | ProjectCoordinator |
| POST | `/reroof/_clock/set_current_utc` | Test-driving endpoint that sets the server's logical clock to `to_iso8601` and answers with `current_utc`. Before any call the logical clock reads exactly 2026-08-01T00:00:00Z and never falls back to real wall-clock time. | ProjectCoordinator |
| POST | `/reroof/_ledger/perturb` | Test-driving endpoint that adds `released_delta_cents` to a project's `credit_released_cents` without touching `credit_authorized_cents`, deliberately unbalancing the credit ledger identity so the defensive settlement guard is reachable. | ProjectCoordinator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_ROLE_NOT_PERMITTED` | 403 Forbidden |
| `ERR_PARTY_NOT_ON_PROJECT` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_PROJECT_NOT_FOUND` | 404 Not Found |
| `ERR_PARTY_NOT_FOUND` | 404 Not Found |
| `ERR_JURISDICTION_NOT_FOUND` | 404 Not Found |
| `ERR_APPROVAL_NOT_FOUND` | 404 Not Found |
| `ERR_CIRCUIT_NOT_FOUND` | 404 Not Found |
| `ERR_UNIT_NOT_FOUND` | 404 Not Found |
| `ERR_BIN_NOT_FOUND` | 404 Not Found |
| `ERR_FINDING_NOT_FOUND` | 404 Not Found |
| `ERR_PERMIT_NOT_FOUND` | 404 Not Found |
| `ERR_INSPECTION_NOT_FOUND` | 404 Not Found |
| `ERR_WINDOW_NOT_FOUND` | 404 Not Found |
| `ERR_SOURCING_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_STALE_PROJECT_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_APPROVAL_ROUND_STALE` | 409 Conflict |
| `ERR_PERMIT_NOT_SUBMITTED` | 409 Conflict |
| `ERR_SETTLEMENT_NOT_READY` | 409 Conflict |
| `ERR_CIRCUIT_NOT_ISOLATED` | 409 Conflict |
| `ERR_PROJECT_POSTURE_FROZEN` | 409 Conflict |
| `ERR_PROJECT_POSTURE_RESTRICTED` | 409 Conflict |
| `ERR_WARRANTY_NOTICE_MISSING` | 409 Conflict |
| `ERR_UNIT_NOT_SERVICEABLE` | 409 Conflict |
| `ERR_CIRCUIT_UNITS_NOT_REINSTALLED` | 409 Conflict |
| `ERR_CROSS_PROJECT_REFERENCE` | 422 Unprocessable Entity |
| `ERR_PARTY_TYPE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_MODEL_MISMATCH_NOT_WAIVED` | 422 Unprocessable Entity |
| `ERR_CIRCUIT_WATT_SPREAD_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_INVALID_WINDOW_BOUNDS` | 422 Unprocessable Entity |
| `ERR_INSPECTION_BACKLOG_VIOLATION` | 422 Unprocessable Entity |
| `ERR_CREW_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_INSPECTION_SLOT_FULL` | 409 Conflict |
| `ERR_BIN_UNIT_TYPE_REJECTED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_SERIAL` | 409 Conflict |
| `ERR_DUPLICATE_BIN_LABEL` | 409 Conflict |
| `ERR_DUPLICATE_CIRCUIT_LABEL` | 409 Conflict |
| `ERR_DUPLICATE_APPROVAL_PARTY` | 409 Conflict |
| `ERR_BIN_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_UPGRADE_BUDGET_EXCEEDED` | 402 Payment Required |
| `ERR_CREDIT_LEDGER_UNBALANCED` | 409 Conflict |
