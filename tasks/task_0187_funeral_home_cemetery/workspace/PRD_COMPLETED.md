# Funeral Home & Cemetery API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Funeral Home & Cemetery management API, a back-office platform that carries a death-care establishment through the full arc of serving a family: intaking a decedent's case, presenting an itemized General Price List (GPL) of services and merchandise, building a funding contract — whether arranged years in advance (preneed) or at the moment of need (at-need) — managing cemetery plot inventory and chapel scheduling, processing death certificates and burial-transit permits, and maintaining a conserved trust ledger that regulators audit.

The domain is unusually constraint-heavy because two distinct bodies of rules collide on every case. The Federal Trade Commission's Funeral Rule mandates that an itemized price disclosure be acknowledged before any charges are committed, and segregation-of-duties principles forbid the same person from both disclosing prices and certifying that a contract is funded. At the same time, state preneed-trust law demands that a mandated fraction of every preneed dollar be deposited into a conserved trust corpus, that the corpus be reconciled like a ledger, and that voiding a contract return every deposited dollar and every reserved plot to its prior state. The API must therefore behave simultaneously as a compliance-audit system and as a reconciling ledger.

A single case advances along two independent axes at once. One axis tracks the *arrangement* of the funeral — from intake through price disclosure, statement issuance, and completion — while a second, independent axis tracks the *interment* readiness driven by permit issuance and cemetery operations. The narrative below walks each lifecycle in turn, but implementers should keep in mind that the two axes interlock only at the final completion gate.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the request is made. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly five roles, spelled precisely as `Admin`, `Arranger`, `TrustOfficer`, `CemeteryClerk`, and `Registrar`. When a recognized role attempts an operation it is not authorized to perform, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The `Admin` is the establishment administrator who configures the funeral home, the GPL catalog, the venues, and the plots, and who holds read access across the system. The `Arranger` is the funeral arranger who handles case intake, FTC disclosure, GPL statement building, contract creation, scheduling, and the case lifecycle; the `Arranger` who acknowledges the disclosure becomes the case's disclosure officer and is the anchor of the segregation-of-duties rule. The `TrustOfficer` manages trust deposits and insurance assignments and marks contracts funded. The `CemeteryClerk` manages plot inventory — reservation, release, and interment. The `Registrar` is the vital-records officer who issues, rejects, and re-evaluates death certificates and burial-transit permits.

All five roles use an **opaque** identity model: in each case `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity, and the server never compares it to any entity's `id`. The server does, however, record the acting identifier where a transition writes it — specifically, acknowledging the FTC disclosure stores the acting `Arranger`'s `X-User-ID` into the case's `disclosure_officer_id`, and the later funding step compares the funding officer's `X-User-ID` against that recorded value to enforce segregation of duties. That comparison is between two header-supplied identifiers, not between a header and an entity primary key.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. A `limit` or `offset` outside its allowed bounds is rejected with `ERR_VALIDATION_OUT_OF_RANGE` (HTTP 422).

Unless an endpoint states otherwise, list results are sorted by `created_at` in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Almost every resource in the system — `FuneralHome`, `GplItem`, `Case`, `StatementLine`, `Contract`, `TrustDeposit`, `InsuranceAssignment`, `Plot`, `Venue`, `Event`, and `Permit` — carries a uniform set of system-managed fields. Each carries an `id` that is a server-minted UUID with no type prefix; a `created_at` timestamp in ISO 8601 UTC with three fractional digits, fixed at creation; an `updated_at` timestamp in the same format, refreshed on every mutation; and a `version`, an integer that starts at 1 on creation and increments by one on every mutation, including mutations caused by cascades. Every entity in this system carries the full set, so there are no resources that omit `updated_at` or `version`.

The `version` field doubles as the optimistic-concurrency token described in §2.7. Whenever any field of a resource changes — including computed fields such as a case's statement totals or a contract's funding figures, and including changes driven indirectly by a cascade from another entity — the server refreshes that resource's `updated_at` and increments its `version`.

### 2.5. Hierarchical Consistency, Cascades, and Nested Retrieval

Many operations touch more than one resource at once, and the system guarantees that every dependent effect is applied atomically with the triggering action. When a parent resource transitions to a non-operational state, its dependent children and their financial commitments are unwound; when a child's change satisfies or violates a parent's state criteria, the parent is transitioned automatically without a separate client request on that parent. Each such automatic mutation independently refreshes the affected resource's `updated_at` and increments its `version`. The two large cascades in this system — the void-and-release cascade that fires when a case is cancelled, and the interment-close cascade that fires when a plot is interred — are described in full in §3, where each link is enumerated.

For any request whose path names more than one resource (for example, a statement line beneath a case, or an event beneath a case), the system validates the identifiers strictly left to right. The first identifier in the path that does not resolve to an existing resource causes immediate rejection with `ERR_NOT_FOUND` (HTTP 404); the parent's existence is always confirmed before any child beneath it is looked up.

### 2.6. Monetary Values, Rounding, and Precision

All monetary amounts in this system are stored and exchanged as integer numbers of cents; there are no fractional-cent values and no decimal currency strings. Two configuration rates are stored as plain fractions on the funeral home: `sales_tax_pct` (for example, 0.08) and `state_trust_pct` (for example, 0.90); these preserve their input precision and are not cents.

Wherever a calculation produces a fractional cent — applying a tax rate to a line subtotal, or applying the state trust fraction to a trustable base — the result is rounded to a whole cent using the **round half up** method (a value exactly halfway between two whole cents rounds up to the larger). Where a calculation is specified to take the floor instead — notably the projected-earnings figure — the fractional part is discarded toward zero rather than rounded. The specific rounding or flooring step that applies to each figure is stated alongside that figure's formula in §3.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and only these two. Both require the client to supply the last `version` it observed of the parent resource, so that a write computed against a stale view is rejected rather than silently overwriting an intervening change.

A reserve-a-plot request must include `expected_plot_version` as a required field carrying the client's last observed `version` of the target plot. If that value does not match the plot's current `version` — for instance because the plot was already reserved for a different case after the client last read it, advancing its version — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). This is evaluated purely as a stale-version comparison, independent of any timing.

A mark-a-contract-funded request must include `expected_contract_version` as a required field carrying the client's last observed `version` of the target contract. Posting a trust deposit or verifying an insurance assignment silently advances a contract's `version` because each recomputes the contract's funding figures; if such a change has occurred since the client read the contract, the supplied `expected_contract_version` will no longer match the contract's current `version` and the request is rejected with `ERR_STALE_VERSION` (HTTP 412), ensuring the funding decision is made against the current `funded_amount_cents`. No other endpoint accepts or requires a version field.

### 2.8. The Conserved Trust Ledger

Preneed trust money is treated as a conserved quantity that must always reconcile. For each contract, the trust corpus is partitioned into a principal component and a credited-earnings component, both tracked through trust-deposit records. The principal corpus, `trust_principal_cents`, is the sum of the amounts of all posted principal deposits minus the sum of the amounts of all posted refund deposits; earnings deposits never count toward it. The credited-earnings figure, `credited_earnings_cents`, is the sum of the amounts of all posted earnings deposits. Each funeral home additionally exposes a rolled-up `trust_balance_cents`, a conserved global quantity equal to the sum, across all of that home's contracts, of each contract's principal corpus plus its credited earnings.

Because the ledger is conserved, voiding a contract must return the corpus to zero. The reversal is applied per kind: each posted principal deposit is left `POSTED` and offset by a newly created compensating `REFUND` deposit of equal amount (the refund's subtraction leg drives `trust_principal_cents` to zero), while each posted earnings deposit is itself flipped to `REFUNDED` — removing it from the posted-earnings set so `credited_earnings_cents` returns to zero — with no separate compensating deposit created for earnings. After the reversal both the home's `trust_balance_cents` and the affected plot's availability are restored exactly to their pre-funding state. The mechanics of the reversal are described with the void cascade in §3.

### 2.9. Validation Ordering

When several checks could reject the same request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication is checked first: a missing header or unknown role yields `ERR_UNAUTHENTICATED`. Authorization is checked second: a recognized but unauthorized role yields `ERR_FORBIDDEN`. Existence is checked third: every path and body resource identifier (across `FuneralHome`, `Case`, `Contract`, `GplItem`, `Plot`, `Venue`, `Event`, `Permit`, `TrustDeposit`, and `InsuranceAssignment`) is resolved left to right, yielding `ERR_NOT_FOUND` on the first miss. Request well-formedness is checked fourth: a missing required field, an invalid enum, an out-of-range integer, or a case-mode/date-of-death mismatch yields `ERR_INVALID_REQUEST` (HTTP 422). Path-segment identifiers are always resolved (existence) before any body well-formedness check, but on create operations whose parent is supplied in the body (for example a `gpl-item`, `case`, `plot`, or `venue` carrying `funeral_home_id`), the body fields are validated for well-formedness first and only then is that body-supplied parent resolved, so a malformed body on such a create yields `ERR_INVALID_REQUEST` even when the referenced parent does not exist. Optimistic-concurrency staleness is checked fifth, on the two guarded endpoints only, yielding `ERR_STALE_VERSION`. Whether the target is in a state from which the requested transition is defined is checked sixth, yielding `ERR_INVALID_STATE` (HTTP 409) when it is not. One operation departs from this sixth-before-seventh ordering: issuing the GFS evaluates its FTC disclosure gate (the seventh concern) ahead of the `DISCLOSED`-state check, as detailed in §3.3.

The remaining business rules follow, and where two business rules guard the same endpoint the lower-numbered concern is evaluated first: the FTC disclosure gate (seventh), segregation of duties (eighth), cross-entity referential gating such as the death-certificate prerequisite, interment readiness, and the completion preconditions (ninth), scheduling-overlap checks (tenth), empty-set guards such as the requirement of at least one selected line at statement issuance (eleventh), and funding sufficiency (twelfth). Each rule's specific trigger condition and error code are described next to the workflow it guards in §3.

## 3. Business Logic & Workflows

### 3.1. Establishment Setup: Funeral Home, Catalog, Venues, and Plots

Before any family is served, an `Admin` stands up the establishment. Creating a funeral home supplies its legal `name`, the `sales_tax_pct` applied to taxable merchandise lines (which must be at least 0 and strictly less than 1), and the `state_trust_pct`, the state-mandated fraction of trustable preneed goods and services that must be deposited to trust (which must be strictly greater than 0 and at most 1). Two further configuration values are optional at creation: `trust_admin_retention_cents`, a flat per-contract administrative amount the home is permitted to retain rather than trust, which must be at least 0 and defaults to 0; and `chapel_buffer_minutes`, the mandatory cleanup buffer enforced between consecutive chapel bookings on the same venue, which must be at least 0 and defaults to 30. A newly created funeral home begins with its computed `trust_balance_cents` at 0.

The `Admin` then populates the **GPL catalog**. Each `GplItem` belongs to a funeral home (supplied as `funeral_home_id`) and carries a `code` that is unique within that home, a display `name`, a `category` that is either `SERVICE` or `MERCHANDISE`, and a `unit_price_cents` that must be at least 0. Three boolean flags refine the item: `taxable`, which defaults to false and should be true only for merchandise, since service lines are tax-exempt; `non_declinable`, which defaults to false and marks the FTC non-declinable basic-services-of-funeral-director fee that must appear on every statement; and `preneed_trustable`, which defaults to true and governs whether the item's value enters the preneed trust requirement base. Every catalog item also carries a system-managed `active` flag, which is set true on creation; the `active` flag is informational and adding a statement line does not gate on it, so a line may be drawn from an item even after it has been deactivated.

A GPL item's price or availability can be updated, supplying a new `unit_price_cents`, a new `active` value, or both. Such an update never retroactively changes statement lines already snapshotted from the item; a new price affects only future statement-line snapshots and at-need plot-charge reads.

Cemetery inventory and chapels round out the setup. A `Plot` belongs to a home via `funeral_home_id` and carries a `section` label, a `plot_code` unique within the home, and a `current_price_cents`. A new plot begins `AVAILABLE`, with no `reserved_case_id` and no `locked_price_cents`. A `Venue` belongs to a home via `funeral_home_id` and carries a `name` and a `capacity` that must be at least 1. Creating a plot is shared between the `Admin` and the `CemeteryClerk`; creating venues and catalog items is reserved to the `Admin`.

### 3.2. Opening a Case and the FTC Disclosure Gate

An `Arranger` opens a **case** by supplying the `funeral_home_id`, the `decedent_name`, and the `case_mode`. The mode is either `AT_NEED`, meaning death has already occurred, or `PRENEED`, meaning arrangements are made in advance. An `AT_NEED` case requires `date_of_death` to be supplied; a `PRENEED` case must omit it (leaving it null). Supplying a date of death on a preneed case, or omitting it on an at-need case, is a malformed request rejected with `ERR_INVALID_REQUEST`. A newly opened case starts with `arrangement_status` of `INTAKE`, `interment_status` of `NOT_READY`, `disclosure_acknowledged` false, and `gfs_issued` false; its computed `statement_total_provisional_cents` and `statement_total_final_cents` both begin at 0, and its `version` begins at 1.

The arrangement axis of a case proceeds `INTAKE → DISCLOSED → ARRANGED → COMPLETED`, with `CANCELLED` reachable as an alternative terminal state; `COMPLETED` and `CANCELLED` are the terminal arrangement states. The first move, acknowledging the FTC funeral-rule GPL disclosure, is performed by an `Arranger` and is allowed only when the case's `arrangement_status` is `INTAKE`. Acknowledging the disclosure sets `disclosure_acknowledged` to true, records the acting `Arranger`'s `X-User-ID` into `disclosure_officer_id` as the segregation-of-duties anchor, advances `arrangement_status` to `DISCLOSED`, and increments the case's `version`. Attempting this transition from any other arrangement state is rejected with `ERR_INVALID_STATE`.

The disclosure is a hard gate on charges. No statement line may be added and no GFS may be issued unless `disclosure_acknowledged` is true; an attempt to add a line or issue the statement before disclosure has been acknowledged is rejected with `ERR_DISCLOSURE_REQUIRED` (HTTP 409). This gate applies to exactly two operations: adding a statement line and issuing the GFS.

### 3.3. Building the Statement: Lines, Selection, and the GFS

With disclosure acknowledged, the `Arranger` builds the itemized statement by adding lines. Adding a line supplies the `gpl_item_id` of the catalog item and an optional `quantity` that defaults to 1 and must be at least 1. At add time the system snapshots the catalog item's attributes onto the new `StatementLine`: the line's `description` is copied from the item's name, and its `category`, `taxable`, `non_declinable`, `preneed_trustable`, and `unit_price_cents` are each snapshotted from the corresponding item field, so later catalog price changes never disturb an existing line. The line records the `case_id` it belongs to and the `gpl_item_id` it was drawn from.

A line's `line_status` advances `PROPOSED → SELECTED → REMOVED`. A line drawn from a non-declinable item is created already `SELECTED` and can never be removed; every other line is created `PROPOSED`. Promoting a proposed line moves it to `SELECTED`; removing a non-mandatory line moves it to `REMOVED`. Attempting to remove a non-declinable line is rejected with `ERR_NON_DECLINABLE_LINE` (HTTP 409). Adding, selecting, or removing a line recomputes the case's provisional statement total.

The **statement total** is computed by rounding each line's tax individually and then summing — never by summing first and rounding once. For a single line, the subtotal is its snapshotted `unit_price_cents` multiplied by its `quantity`; if the line is taxable, its tax is that subtotal multiplied by the home's `sales_tax_pct`, rounded half up to a whole cent, and if the line is not taxable its tax is 0; the line's contribution is the subtotal plus that tax. The provisional total, stored in `statement_total_provisional_cents`, is the sum of these line contributions over every line whose `line_status` is `PROPOSED` or `SELECTED`. The final total, stored in `statement_total_final_cents`, is the sum of the same line contributions but over only the lines whose `line_status` is `SELECTED`; removed lines are excluded from both totals. Because the provisional total counts proposed lines and the final total does not, dropping a proposed line at issuance changes the figure.

Issuing the **Goods & Services Statement (GFS)** is the `Arranger`'s move from `DISCLOSED` to `ARRANGED`. It is allowed only when the case is `DISCLOSED`, `disclosure_acknowledged` is true, at least one `SELECTED` statement line exists, and a contract already exists for the case. On this operation the FTC disclosure gate is evaluated ahead of the arrangement-state check (an exception to the §2.9 general ordering, where state would precede business rules): an undisclosed case is rejected with `ERR_DISCLOSURE_REQUIRED` even when its `arrangement_status` is not `DISCLOSED` (for example still `INTAKE`). Once disclosure is acknowledged, issuing from a non-`DISCLOSED` state is rejected with `ERR_INVALID_STATE`; then issuing before a contract exists is rejected with `ERR_CONTRACT_REQUIRED` (HTTP 409); then issuing with zero selected lines is rejected with `ERR_EMPTY_STATEMENT` (HTTP 409). On success the system recomputes `statement_total_final_cents` over the selected lines (per-line rounded tax then summed), sets `gfs_issued` to true to lock that final total, recomputes the contract's `contract_amount_cents` and `trust_required_cents` from the locked figure, advances `arrangement_status` to `ARRANGED`, and increments the case's `version`.

### 3.4. The Funding Contract and Its Funding Figures

Exactly one **contract** is created per case by an `Arranger`, supplying the `funding_type`: `PRENEED_TRUST`, `AT_NEED_DIRECT`, or `INSURANCE_ASSIGNMENT`. The contract records its `case_id`, begins in `DRAFT`, and immediately computes its funding figures. Attempting to create a second contract for a case that already has one is rejected with `ERR_CONTRACT_EXISTS` (HTTP 409). The contract status machine runs `DRAFT → PENDING_FUNDING → FUNDED → SETTLED`, with `VOID` reachable from any non-terminal status and `PENDING_FUNDING` able to revert to `DRAFT` for preneed amendment; `SETTLED` and `VOID` are terminal.

A contract carries several computed figures. `contract_amount_cents` is the amount the contract must cover: it mirrors the case's `statement_total_final_cents` once the GFS has been issued, and before that it mirrors `statement_total_provisional_cents`. `trust_required_cents` is the required trust principal and is described below. `trust_principal_cents` and `credited_earnings_cents` are the conserved principal and earnings figures defined in §2.8. `projected_earnings_cents` is a forward-looking projection defined below. `funded_amount_cents` is the dual-variant funding figure also defined below.

The **required trust principal**, `trust_required_cents`, depends on the funding type. For any contract that is not `PRENEED_TRUST`, it is 0. For a `PRENEED_TRUST` contract, first form the trustable base by summing the per-line contributions (computed with the same per-line rounding as the statement total) over only the lines that are both `SELECTED` and flagged `preneed_trustable`; take that trustable base multiplied by the home's `state_trust_pct`, rounded half up to a whole cent, to get the gross requirement; then subtract the home's `trust_admin_retention_cents` and take the larger of 0 and the result. In other words, the requirement is the gross trust amount less the admin retention, floored at 0 so it can never go negative. The trust gate compares the contract's `trust_principal_cents` (principal only) against this `trust_required_cents`.

The **projected trust earnings**, `projected_earnings_cents`, is a forward-looking figure computed over the principal corpus only and excludes already-credited earnings. For a `PRENEED_TRUST` contract it is the contract's `trust_principal_cents` multiplied by a projection rate of three percent, with the fractional cent discarded by taking the floor; for any other funding type it is 0. This figure is recomputed whenever a principal deposit is posted and whenever the contract is submitted for funding.

The **funded amount**, `funded_amount_cents`, is computed by one of three rules according to `funding_type`. For a `PRENEED_TRUST` contract it is the sum of `trust_principal_cents`, `credited_earnings_cents`, and `projected_earnings_cents` — that is, the realized principal corpus plus credited interest plus the forward-looking projection, a projected maturity value. For an `INSURANCE_ASSIGNMENT` contract it is the sum of the `assigned_value_cents` of every insurance assignment on the contract whose status is `VERIFIED`. For an `AT_NEED_DIRECT` contract it is the chronological sum of the amounts of every posted principal deposit, replayed in order of `posted_at` ascending with `created_at` ascending as the tie-break (never by `id`); this variant counts only realized posted principal payments, with no earnings and no projection. The funded amount is recomputed on every event that could change it: posting a trust deposit, verifying or releasing an insurance assignment, and submitting the contract for funding or marking it funded.

### 3.5. Trust Deposits and Insurance Assignments

A `TrustOfficer` funds a contract through one of two channels depending on its funding type. Posting a **trust deposit** to a contract supplies its `kind` — `PRINCIPAL` for a client payment into trust, `EARNINGS` for credited interest, or `REFUND` for the subtraction leg of a reversal — and an `amount_cents` that must be at least 1; the sign is implied by the kind, with `REFUND` subtracting. The deposit records its `contract_id`, is created with `status` `POSTED`, and is stamped with a `posted_at` server timestamp that serves as the chronological ordering key for at-need ledger replay (with `created_at` as tie-break). A deposit's `status` runs `POSTED → REFUNDED`; refund-kind deposits are themselves created `POSTED` and represent the subtraction leg of a reversal. Posting a deposit recomputes the contract's `trust_principal_cents`, `projected_earnings_cents`, and `funded_amount_cents`, recomputes the home's `trust_balance_cents`, and increments the contract's `version`.

Alternatively, a `TrustOfficer` attaches an **insurance assignment** to a contract, supplying the `policy_number`, the `carrier`, and the `assigned_value_cents` — the irrevocably assigned death benefit available to fund the contract, which must be at least 1. The assignment records its `contract_id` and begins `PENDING`. Its status runs `PENDING → VERIFIED → RELEASED`, with `DECLINED` reachable from `PENDING`; only a `VERIFIED` assignment counts toward `funded_amount_cents`. Verifying an assignment is allowed only when it is `PENDING` and only when the parent contract's `funding_type` is `INSURANCE_ASSIGNMENT`; verifying against a contract of a different funding type is rejected with `ERR_FUNDING_TYPE_MISMATCH` (HTTP 409). Verification advances the assignment to `VERIFIED`, recomputes the contract's `funded_amount_cents` so it now includes the assigned value, increments the assignment's `version`, and increments the contract's `version`. Declining a `PENDING` assignment moves it to `DECLINED` and increments the assignment's `version`. An assignment is moved to `RELEASED` only as part of the contract-void cascade; releasing recomputes the contract's `funded_amount_cents` so it drops the assigned value and increments the assignment's `version`. Attempting to verify, decline, or otherwise act on an assignment that is not in the required source state is rejected with `ERR_INVALID_STATE`.

### 3.6. Submitting and Funding the Contract

Once the GFS is issued, the `Arranger` submits the contract for funding, moving it from `DRAFT` to `PENDING_FUNDING`. This is allowed only when the contract is `DRAFT` and the case's `gfs_issued` is true; submitting before the GFS has been issued is rejected with `ERR_GFS_NOT_ISSUED` (HTTP 409), and submitting from a non-`DRAFT` state is rejected with `ERR_INVALID_STATE`. Submission recomputes the contract's `trust_required_cents` and `funded_amount_cents` and increments its `version`.

A preneed contract sometimes needs revision. An `Arranger` may reopen a contract, bouncing it from `PENDING_FUNDING` back to `DRAFT` so the statement can be amended and then resubmitted — a deliberate cyclic loop. Reopening is allowed only when the contract is `PENDING_FUNDING` and its `funding_type` is `PRENEED_TRUST`; only preneed contracts may be reopened, and attempting to reopen any other funding type is rejected with `ERR_NOT_AMENDABLE` (HTTP 409). Reopening from a non-`PENDING_FUNDING` state is rejected with `ERR_INVALID_STATE`. Reopening increments the contract's `version`.

Marking a contract **funded** is the `TrustOfficer`'s move from `PENDING_FUNDING` to `FUNDED`, and it carries the `expected_contract_version` OCC token described in §2.7. Several gates apply, in this order. First the OCC token must match the contract's current `version`, or the request is rejected with `ERR_STALE_VERSION`. The contract must be `PENDING_FUNDING`, or the request is rejected with `ERR_INVALID_STATE`. The funding officer's `X-User-ID` must differ from the case's recorded `disclosure_officer_id` — the `Arranger` who acknowledged the disclosure may not also fund the contract — and a match is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409). The contract must be sufficiently funded: `funded_amount_cents` must be at least `contract_amount_cents`, and a shortfall is rejected with `ERR_FUNDING_SHORTFALL` (HTTP 409). Additionally, for a `PRENEED_TRUST` contract, `trust_principal_cents` must be at least `trust_required_cents`, and an underfunded preneed trust is rejected with `ERR_TRUST_UNDERFUNDED` (HTTP 409). On success the contract advances to `FUNDED` and its `version` increments.

### 3.7. Permits, Interment Readiness, and the Interment Axis

The interment axis of a case is independent of its arrangement axis and runs `NOT_READY → READY → INTERRED`, with `INTERRED` terminal; it is reset to `NOT_READY` when a case is cancelled. This axis is driven by permits and cemetery operations rather than by the `Arranger`'s arrangement steps.

A **permit** is applied for against a case — an operation shared between the `Arranger` and the `Registrar` — supplying the `permit_type`, which is either `DEATH_CERTIFICATE` or `BURIAL_TRANSIT`. A permit records its `case_id`, begins `APPLIED`, and has no `reference_number` until it is issued. Its status runs `APPLIED → ISSUED`, with `REJECTED` reachable from `APPLIED` and `REJECTED` able to revert to `APPLIED` for a re-apply loop; `ISSUED` is terminal. The `Registrar` issues, rejects, and re-applies permits.

Issuing a permit supplies the `reference_number` to record and is allowed only when the permit is `APPLIED`; issuing a permit not in `APPLIED` is rejected with `ERR_PERMIT_NOT_APPLIED` (HTTP 409). A burial-transit permit carries an extra prerequisite: an `ISSUED` `DEATH_CERTIFICATE` permit must already exist for the same case, and attempting to issue a burial-transit permit without one is rejected with `ERR_DEATH_CERT_REQUIRED` (HTTP 409). Issuing sets the `reference_number`, increments the permit's `version`, and then performs a cross-entity bubble-up: if this issuance results in both a `DEATH_CERTIFICATE` and a `BURIAL_TRANSIT` permit being `ISSUED` for the case while the case's `interment_status` is still `NOT_READY`, the case's `interment_status` advances to `READY` and the case's `version` increments. Phrased as the interment-axis transition, a case moves `NOT_READY → READY` automatically exactly when one issued death-certificate permit and one issued burial-transit permit both exist for the case.

Rejecting an `APPLIED` permit moves it to `REJECTED` and increments its `version`; rejecting a permit not in `APPLIED` is rejected with `ERR_PERMIT_NOT_APPLIED`. Re-applying a `REJECTED` permit moves it back to `APPLIED` so it can be re-evaluated, and increments its `version`; re-applying a permit not in `REJECTED` is rejected with `ERR_PERMIT_NOT_REJECTED` (HTTP 409).

### 3.8. Plot Reservation, Pricing, and Interment

A `CemeteryClerk` reserves an `AVAILABLE` plot for a case, supplying the `case_id` and the `expected_plot_version` OCC token. Reservation is allowed only when the plot is `AVAILABLE` — a plot not in `AVAILABLE` is rejected with `ERR_PLOT_NOT_AVAILABLE` (HTTP 409) — and only when the target case exists and is neither `CANCELLED` nor `COMPLETED`; a target case whose `arrangement_status` is `CANCELLED` or `COMPLETED` is rejected with `ERR_INVALID_STATE` (HTTP 409). The OCC token must match the plot's current `version` per §2.7, or the request is rejected with `ERR_STALE_VERSION`. These checks are evaluated in the order: target-case existence, then OCC staleness, then the plot-`AVAILABLE` state check, then the target-case active-state check. On success the plot moves to `RESERVED`, its `reserved_case_id` is set to the supplied case, and its `locked_price_cents` is snapshotted from `current_price_cents` as a price lock; the plot's `version` increments.

The **plot charge** depends on the reserving case's `case_mode`. For a `PRENEED` case the charge is the plot's `locked_price_cents` — the price snapshotted at reservation, immune to later GPL price changes. For an `AT_NEED` case the charge is the plot's live `current_price_cents`, so a later price change moves the charge.

A reserved plot can be released back to `AVAILABLE` by a `CemeteryClerk`. Release is allowed only when the plot is `RESERVED` — releasing a plot not in `RESERVED` is rejected with `ERR_PLOT_NOT_RESERVED` (HTTP 409) — and only when the case currently holding the plot has not already reached `INTERRED` on its interment axis; attempting to release a plot whose holding case is `INTERRED` is rejected with `ERR_INVALID_STATE` (HTTP 409). Release clears `reserved_case_id` and `locked_price_cents` back to null and increments the plot's `version`.

**Interment** is the `CemeteryClerk`'s move performed on a plot. It is allowed only when the plot is `RESERVED` (otherwise `ERR_PLOT_NOT_RESERVED`) and the interment axis of the case holding that plot is `READY` (otherwise `ERR_INTERMENT_NOT_READY`, HTTP 409). Interment is the head of a two-link close cascade: the plot's status advances to `INTERRED`, and because the plot has become `INTERRED`, the reserved case's `interment_status` advances to `INTERRED`; the plot's `version` and the case's `version` both increment. The case affected is the plot's own `reserved_case_id`.

### 3.9. Scheduling Chapel and Graveside Events

An `Arranger` schedules an **event** against a case, supplying the `resource_kind`, the `resource_id`, the `starts_at`, and, for chapel events, the `ends_at`. The kind is either `CHAPEL`, which books a venue, or `GRAVESIDE`, which books a plot — a polymorphic reference in which `resource_id` names a venue when the kind is `CHAPEL` and names a plot when the kind is `GRAVESIDE`. The event records its `case_id` and begins `SCHEDULED`; its status simply runs `SCHEDULED → CANCELLED`.

The two kinds are scheduled with different time semantics. A `CHAPEL` event occupies a half-open interval from `starts_at` (inclusive) up to but not including `ends_at`, at minute granularity, and `ends_at` is required for it. A `GRAVESIDE` event uses only the calendar date of `starts_at` (taken in UTC) and ignores `ends_at`, occupying the whole day exclusively; any supplied `ends_at` is discarded and the stored event's `ends_at` is null. Overlap is enforced against existing `SCHEDULED` events on the same resource: two chapel bookings on the same venue conflict if their intervals overlap once each interval's end is extended by the home's `chapel_buffer_minutes` of cleanup buffer; concretely, the conflict test treats the new booking as `[starts_at, ends_at + buffer)` and each existing booking as `[its starts_at, its ends_at + buffer)` and reports a conflict when those half-open intervals overlap. Because the intervals are half-open, a back-to-back gap of exactly `chapel_buffer_minutes` between consecutive bookings does not conflict (the later booking may start exactly `buffer` minutes after the earlier one ends), while any smaller gap does. Two graveside bookings on the same plot conflict if they fall on the same calendar date. A conflicting booking is rejected with `ERR_SCHEDULE_CONFLICT` (HTTP 409).

An `Arranger` may cancel a scheduled event; cancellation is allowed only when the event is `SCHEDULED` (otherwise `ERR_INVALID_STATE`), moves the event to `CANCELLED`, increments its `version`, and frees the resource interval so a later overlapping booking on the same venue or plot succeeds.

### 3.10. Completing a Case

Completing a case is the `Arranger`'s final arrangement move, from `ARRANGED` to `COMPLETED`. It is allowed only when the case's `arrangement_status` is `ARRANGED`, its `interment_status` is `INTERRED`, and its contract's `status` is `FUNDED`. Attempting completion while the interment is not yet `INTERRED` is rejected with `ERR_INTERMENT_INCOMPLETE` (HTTP 409); attempting it while the contract is not `FUNDED` is rejected with `ERR_CONTRACT_NOT_FUNDED` (HTTP 409); attempting it from a non-`ARRANGED` arrangement state is rejected with `ERR_INVALID_STATE`. On success the case's `arrangement_status` advances to `COMPLETED`, the contract is automatically advanced from `FUNDED` to `SETTLED`, and the case's `version` (and the contract's `version`) increment.

### 3.11. Cancelling a Case: The Void-and-Release Cascade

Cancelling a case is the `Arranger`'s emergency exit and the head of a four-link cascade that conserves both the trust ledger and plot availability. Cancellation is allowed whenever the case's `arrangement_status` is `INTAKE`, `DISCLOSED`, or `ARRANGED`; from any other state it is rejected with `ERR_INVALID_STATE`. The case's `arrangement_status` becomes `CANCELLED`, its `interment_status` resets to `NOT_READY`, and its `version` increments.

The cascade then unwinds the case's commitments. As the first link, if a contract exists for the case and it is neither `VOID` nor `SETTLED`, the contract's `status` becomes `VOID`. Voiding the contract drives the remaining links. As the second link, the corpus is reversed per kind: for every posted `PRINCIPAL` deposit on the contract the system creates a compensating `REFUND` trust deposit of equal amount while leaving the original principal deposit `POSTED` (the new `REFUND` leg is the subtraction term, so `trust_principal_cents` returns to 0); for every posted `EARNINGS` deposit it instead marks that original deposit `REFUNDED` and creates no compensating deposit, so `credited_earnings_cents` returns to 0; and every `VERIFIED` insurance assignment on the contract is moved to `RELEASED`. As the third link, if a plot has this case as its `reserved_case_id` and is `RESERVED`, the plot is released — its `status` returns to `AVAILABLE`, its `reserved_case_id` is cleared to null, and its `locked_price_cents` is cleared to null — because the contract has voided. As the fourth link, every `SCHEDULED` event of the case is moved to `CANCELLED`. The contract's `version` increments, and the versions of every affected trust deposit, plot, and event row are bumped as well. After the cascade, the home's `trust_balance_cents` and the released plot's availability are both restored to their pre-funding state.

## 4. Endpoint Definitions

Operations that create a new, distinct resource return `201 Created`; operations that modify or transition an existing resource, and all read operations, return `200 OK`. Every request requires the `X-User-ID` and `X-User-Role` headers described in §2.1. Request and response bodies are not enumerated in this table — the workflows in §3 are the authoritative source for what each operation accepts and produces.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/funeral-homes` | Create a funeral home (tax/trust rates, chapel buffer) | Admin |
| GET | `/funeral-homes/{homeId}` | Get a funeral home, including computed trust balance | Admin, Arranger, TrustOfficer, CemeteryClerk, Registrar |
| POST | `/gpl-items` | Create a GPL price-list item | Admin |
| GET | `/gpl-items/{itemId}` | Get a GPL item | Admin, Arranger |
| GET | `/gpl-items` | List GPL items, optionally by funeral home | Admin, Arranger |
| PATCH | `/gpl-items/{itemId}` | Update a GPL item's price or active flag | Admin |
| POST | `/cases` | Open a decedent case (intake) | Arranger |
| GET | `/cases/{caseId}` | Get a case with both status axes and computed totals | Admin, Arranger, TrustOfficer, CemeteryClerk, Registrar |
| GET | `/cases` | List cases, optionally by funeral home | Admin, Arranger, TrustOfficer, CemeteryClerk, Registrar |
| POST | `/cases/{caseId}/acknowledge-disclosure` | Acknowledge FTC funeral-rule GPL disclosure | Arranger |
| POST | `/cases/{caseId}/issue-gfs` | Issue the GFS and lock the final total | Arranger |
| POST | `/cases/{caseId}/complete` | Complete a case; settles the contract | Arranger |
| POST | `/cases/{caseId}/cancel` | Cancel a case; head of the void-and-release cascade | Arranger |
| POST | `/cases/{caseId}/statement-lines` | Add a GPL item as a statement line | Arranger |
| GET | `/cases/{caseId}/statement-lines` | List statement lines for a case | Admin, Arranger |
| GET | `/statement-lines/{lineId}` | Get a single statement line | Admin, Arranger |
| GET | `/statement-lines` | List statement lines, optionally by case or GPL item | Admin, Arranger |
| POST | `/cases/{caseId}/statement-lines/{lineId}/select` | Promote a proposed line to selected | Arranger |
| POST | `/cases/{caseId}/statement-lines/{lineId}/remove` | Remove a non-mandatory line | Arranger |
| POST | `/cases/{caseId}/contract` | Create the single contract for a case | Arranger |
| GET | `/contracts/{contractId}` | Get a contract with computed funding fields | Admin, Arranger, TrustOfficer |
| GET | `/contracts` | List contracts, optionally by case | Admin, Arranger, TrustOfficer |
| POST | `/contracts/{contractId}/submit-for-funding` | Move a contract to pending funding | Arranger |
| POST | `/contracts/{contractId}/reopen` | Reopen a preneed contract for amendment | Arranger |
| POST | `/contracts/{contractId}/mark-funded` | Mark a contract funded (OCC + segregation + funding checks) | TrustOfficer |
| POST | `/contracts/{contractId}/trust-deposits` | Post a trust deposit (principal/earnings/refund) | TrustOfficer |
| GET | `/contracts/{contractId}/trust-deposits` | List trust deposits for a contract | Admin, TrustOfficer |
| GET | `/trust-deposits/{depositId}` | Get a single trust deposit | Admin, TrustOfficer |
| GET | `/trust-deposits` | List trust deposits, optionally by contract | Admin, TrustOfficer |
| POST | `/contracts/{contractId}/insurance-assignments` | Attach an insurance assignment to a contract | TrustOfficer |
| GET | `/insurance-assignments/{assignmentId}` | Get an insurance assignment | Admin, TrustOfficer |
| GET | `/insurance-assignments` | List insurance assignments, optionally by contract | Admin, TrustOfficer |
| POST | `/insurance-assignments/{assignmentId}/verify` | Verify an assignment; counts toward funded amount | TrustOfficer |
| POST | `/insurance-assignments/{assignmentId}/decline` | Decline an assignment | TrustOfficer |
| POST | `/plots` | Create a cemetery plot | Admin, CemeteryClerk |
| GET | `/plots/{plotId}` | Get a plot | Admin, Arranger, CemeteryClerk |
| GET | `/plots` | List plots, optionally by funeral home or reserving case | Admin, Arranger, CemeteryClerk |
| POST | `/plots/{plotId}/reserve` | Reserve an available plot for a case (OCC-guarded) | CemeteryClerk |
| POST | `/plots/{plotId}/release` | Release a reserved plot back to available | CemeteryClerk |
| POST | `/plots/{plotId}/inter` | Perform interment; bubbles case interment to interred | CemeteryClerk |
| POST | `/venues` | Create a chapel/venue | Admin |
| GET | `/venues/{venueId}` | Get a venue | Admin, Arranger, CemeteryClerk |
| GET | `/venues` | List venues, optionally by funeral home | Admin, Arranger, CemeteryClerk |
| POST | `/cases/{caseId}/events` | Schedule a chapel or graveside event | Arranger |
| GET | `/cases/{caseId}/events` | List events for a case | Admin, Arranger, CemeteryClerk |
| GET | `/events/{eventId}` | Get a single event | Admin, Arranger, CemeteryClerk |
| GET | `/events` | List events, optionally by case or resource | Admin, Arranger, CemeteryClerk |
| POST | `/cases/{caseId}/events/{eventId}/cancel` | Cancel a scheduled event | Arranger |
| POST | `/cases/{caseId}/permits` | Apply for a permit (death certificate / burial-transit) | Arranger, Registrar |
| GET | `/cases/{caseId}/permits` | List permits for a case | Admin, Arranger, Registrar |
| GET | `/permits/{permitId}` | Get a permit | Admin, Arranger, Registrar |
| GET | `/permits` | List permits, optionally by case | Admin, Arranger, Registrar |
| POST | `/permits/{permitId}/issue` | Issue a permit; may make a case ready for interment | Registrar |
| POST | `/permits/{permitId}/reject` | Reject a permit | Registrar |
| POST | `/permits/{permitId}/reapply` | Re-apply a rejected permit | Registrar |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DISCLOSURE_REQUIRED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_DEATH_CERT_REQUIRED` | 409 |
| `ERR_INTERMENT_NOT_READY` | 409 |
| `ERR_INTERMENT_INCOMPLETE` | 409 |
| `ERR_CONTRACT_NOT_FUNDED` | 409 |
| `ERR_CONTRACT_REQUIRED` | 409 |
| `ERR_GFS_NOT_ISSUED` | 409 |
| `ERR_EMPTY_STATEMENT` | 409 |
| `ERR_FUNDING_SHORTFALL` | 409 |
| `ERR_TRUST_UNDERFUNDED` | 409 |
| `ERR_SCHEDULE_CONFLICT` | 409 |
| `ERR_PLOT_NOT_AVAILABLE` | 409 |
| `ERR_PLOT_NOT_RESERVED` | 409 |
| `ERR_NON_DECLINABLE_LINE` | 409 |
| `ERR_NOT_AMENDABLE` | 409 |
| `ERR_FUNDING_TYPE_MISMATCH` | 409 |
| `ERR_PERMIT_NOT_APPLIED` | 409 |
| `ERR_PERMIT_NOT_REJECTED` | 409 |
| `ERR_CONTRACT_EXISTS` | 409 |
| `ERR_VALIDATION_OUT_OF_RANGE` | 422 |
