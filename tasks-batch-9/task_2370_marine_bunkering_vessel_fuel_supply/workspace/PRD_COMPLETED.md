# Marine Bunkering & Vessel Fuel Supply API — Product Requirements Document

## 1. Introduction

Selling bunker fuel to ocean-going vessels is one of the few commercial activities where a single operational slip is simultaneously a regulatory offence, a financial loss and an environmental incident. A stem nominated against the wrong grade can put a vessel in breach of MARPOL Annex VI inside an Emission Control Area; a barge that arrives without a certified containment boom cannot legally begin pumping; a tank sounding that disagrees with the mass-flow meter by more than a tonne is evidence that nobody actually knows how much fuel changed hands. Today all of this is coordinated by phone, spreadsheet and PDF, and the supplier discovers its exposure only when the customer disputes the invoice.

This document specifies the API that replaces that coordination. The system carries a vessel bunker nomination from intake, through emission-control compliance review, credit clearance, barge or truck scheduling with port-authority coordination, physical transfer, quantity reconciliation by soundings, meters and independent joint survey, issuance of the MARPOL bunker delivery note with its mandatory retained sample, laboratory-backed quality claims and remediation, and finally indexed invoicing with a bunker adjustment factor and credit-note settlement. Spill prevention runs alongside every one of those stages: an incident during a delivery suspends that delivery, penalises the asset's compliance score and, when severe, quarantines the asset and unwinds every other slot it was holding.

Two design commitments shape the whole specification. First, **compliance and fulfilment are independent dimensions** — a nomination's regulatory standing and its logistics progress advance on separate state machines that live on the same record, as do a delivery order's physical progress and its quantity-agreement standing. Second, **every derived figure is reproducible**: rounding order, tie-breaks in price selection, the sequence of steps in a remediation credit, and the ranking of candidate barges are all pinned, because a bunker supplier that cannot reproduce a number to the cent cannot defend it in arbitration.

## 2. Global Specifications & System-Wide Principles

This section defines the contracts and cross-cutting principles that apply to every endpoint in the system. Where a rule here conflicts with an intuitive reading of the business narrative in §3, the rule here governs.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which they act. If either header is absent, or if `X-User-Role` is not one of the role names defined below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are valid but the declared role is not authorised for the requested operation, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403).

The system recognises exactly seven roles: `OpsCoordinator`, `ComplianceOfficer`, `Surveyor`, `CreditController`, `LabTechnician`, `CustomerRep`, and `BargeMaster`.

The bunker operations desk acts as `OpsCoordinator`: it maintains reference data, takes in nominations, confirms stems, schedules barges and trucks, records port clearance, cancels orders, issues bunker delivery notes and releases retained samples. The regulatory desk acts as `ComplianceOfficer`: emission-control sulfur and documentation review, spill containment sign-off, incident closure and release of quarantined assets. An independent `Surveyor` performs joint surveys and resurveys, agrees resurveyed quantities and proposes claim remediations. The credit and billing desk acts as `CreditController`: customer onboarding, credit reviews, index quotes, invoicing and the booking of remediation credits. The testing laboratory acts as `LabTechnician` and files analyses of released samples.

Five of these roles are operator desks whose identity is not a persisted record. When `X-User-Role` is `OpsCoordinator`, `ComplianceOfficer`, `Surveyor`, `CreditController`, or `LabTechnician`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow demands an audit trail — as `compliance_reviewer_user_id` on a nomination, as `issued_by_user_id` on a bunker delivery note, as `proposed_by_user_id` and `accepted_by_user_id` on a quality claim, and as `analyzed_by_user_id` on a laboratory analysis — but it never compares such an identifier to any entity's `id`.

The remaining two roles are entity-backed. When `X-User-Role` is `CustomerRep`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's customer foreign-key field to `X-User-ID`, and a mismatch is rejected with `ERR_CUSTOMER_SCOPE_VIOLATION` (HTTP 403). Concretely, that scope check guards six operations: raising a quality claim, requesting a retest on a claim, submitting a quantity decision on a delivery order, reading a customer's credit exposure, listing nominations, and listing quality claims — on the two list endpoints the rejection fires only when the request carries an explicit `customer_id` filter naming a different customer, because a listing without that filter is silently narrowed to the acting customer instead. When `X-User-Role` is `BargeMaster`, `X-User-ID` is the `id` of the acting `DeliveryAsset`; a `BargeMaster` may only act on a delivery order whose `asset_id` equals `X-User-ID`, and a mismatch is rejected with `ERR_ASSET_NOT_ASSIGNED` (HTTP 403). That check guards three operations: starting pumping, completing pumping, and reporting a spill incident.

Segregation of duties is enforced independently of role membership, and its violation carries `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Two pairings are policed: the `OpsCoordinator` whose `X-User-ID` is recorded as `issued_by_user_id` on a bunker delivery note must differ from the `compliance_reviewer_user_id` recorded on the nomination behind that note, and the `CreditController` who books a remediation credit must have an `X-User-ID` differing from the `proposed_by_user_id` recorded when the remediation was proposed.

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

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_` followed by twenty random uppercase alphanumeric characters.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, read from the logical clock of §2.4 rather than from wall-clock time.
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

List endpoints are paginated through two query parameters. `limit` sets the maximum number of records returned; when omitted it defaults to 10, its minimum accepted value is 1 and its maximum accepted value is 100. `offset` sets the number of records to skip and defaults to 0; negative offsets are not accepted. A `limit` outside the range 1 through 100, a negative `offset`, a `limit` or `offset` that is not a valid integer, and a list filter whose value is not a member of the filtered field's enumeration are all payload violations and are rejected with `ERR_INVALID_REQUEST` (HTTP 422).

Unless a specific endpoint states otherwise, list results are sorted by `created_at` in ascending order; because the logical clock makes records that share an instant routine, rows carrying the same `created_at` are ordered by the sequence in which the server created them. The one documented exception is the per-grade index quote listing, which is ordered by `quote_date` with the most recent quote first, ties on `quote_date` resolved in favour of the later `created_at` and then the later creation sequence.

Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the number of records matching the filter before pagination is applied and `has_more` indicates whether records remain beyond the current page.

### 2.4. The Logical Clock

The server keeps a **logical UTC clock** rather than reading wall-clock time. Before any clock-setting call has been made, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it must never fall back to real wall-clock time. An `OpsCoordinator` may advance or set the clock through an administrative test-driving capability that accepts a single instant, supplied as `to_iso8601`; the call returns HTTP 200 and no resource payload. Every subsequent evaluation of sample custody, claim windows, notice periods, slot admissibility and spill-decay ageing uses the new instant.

All timestamps the system persists or emits — `created_at`, `updated_at`, `cleared_at`, `sample_retention_until`, `sample_released_at`, `issued_at`, `due_date`, `closed_at`, `quote_date`, `pricing_date`, `reported_at`, `window_start`, `window_end`, `slot_start`, `slot_end` — are ISO 8601 UTC instants.

### 2.5. Record Identity, Versioning and Audit Fields

Every resource in the system is addressed by an `id`, which is a server-minted UUID carrying no type prefix; wherever an endpoint path contains an identifier segment, that segment is the target resource's `id`. Every resource also carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording when the record was first written.

All resources except index quotes additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by one on every mutation of the record. This includes mutations the client did not directly request: when a cascade recomputes a customer's balances, a nomination's fulfilment standing or an asset's committed tonnage, that record's `updated_at` is refreshed and its `version` is incremented in the same way an explicit write would. Within a single request, however, a record's `version` advances by at most one however many times that request writes to it, and a record the request itself creates is never additionally touched: it is returned at `version` 1.

An `IndexQuote` is immutable once posted. It therefore carries only `id` and `created_at`: it has neither `updated_at` nor `version`, and both fields are absent from its representation.

### 2.6. Parallel Status Dimensions and Cascade Propagation

Two of the system's records track two independent lifecycles at once, and this is deliberate rather than accidental. A `Nomination` carries `compliance_status`, its regulatory dimension, alongside `fulfillment_status`, its logistics dimension; the two advance independently, so a nomination may legitimately sit in `DRAFT` fulfilment while already `APPROVED` for compliance. A `DeliveryOrder` carries `logistics_status`, its physical-delivery dimension, alongside `measurement_status`, its quantity-agreement dimension, and again the two advance independently — an order can be physically `DELIVERED` while its measurement dimension is still `FIGURES_RECORDED` awaiting a surveyor.

Because delivery, billing and safety records reference one another, many operations mutate more than one record. Where §3 describes a cascade, every named secondary effect is mandatory, and cascades are transitive: a spill incident of major severity suspends its own delivery order, quarantines the asset, cancels that asset's other scheduled and cleared orders, and pushes each of those orders' nominations back to awaiting-schedule — four records deep from a single request. Each affected record independently refreshes `updated_at` and increments `version`.

### 2.7. Reference Resolution Order

Requests that name several records — in the path, in the body, or both — are validated for existence in a fixed left-to-right, outer-to-inner order, and the first identifier that fails to resolve determines the error returned. The order of resolution across the system is: `port_id`, then `grade_id`, then `customer_id`, then `asset_id`, then `nomination_id`, then `delivery_order_id`, then `bdn_id`, then `claim_id`, then `retest_of_analysis_id`, then an invoice `id`, then a spill incident `id`. The corresponding rejections are `ERR_PORT_NOT_FOUND`, `ERR_FUEL_GRADE_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`, `ERR_NOMINATION_NOT_FOUND`, `ERR_DELIVERY_ORDER_NOT_FOUND`, `ERR_BDN_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_LAB_ANALYSIS_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND` and `ERR_SPILL_INCIDENT_NOT_FOUND`, each carrying HTTP 404. A nomination intake naming a non-existent port and a non-existent grade in the same payload therefore reports the port failure, never the grade failure. A non-null `retest_of_analysis_id` must resolve to an existing laboratory analysis; when it is omitted the check does not apply.

### 2.8. Validation Precedence

When a single request could fail several checks, the system evaluates them in a fixed precedence and returns the first failure. Reading in order:

1. Header authentication — `ERR_UNAUTHENTICATED`.
2. Role authorisation for the endpoint — `ERR_ROLE_NOT_PERMITTED`.
3. Existence of every referenced record, in the order given in §2.7 — the various not-found rejections.
4. Customer scope for a `CustomerRep` — `ERR_CUSTOMER_SCOPE_VIOLATION`.
5. Asset assignment for a `BargeMaster` — `ERR_ASSET_NOT_ASSIGNED`.
6. Payload shape: required fields present, declared types respected, enum members valid, declared decimal scales respected, quantities strictly positive where declared so, and pagination parameters in range — `ERR_INVALID_REQUEST`; an optional field supplied explicitly as `null` counts as absent and takes its documented default.
7. Stale-version guards — `ERR_STALE_NOMINATION_VERSION`, then `ERR_STALE_CLAIM_VERSION`.
8. State legality, in this internal order: nomination state, compliance approval, order logistics state, measurement agreement, measurement state legality, an already-issued delivery note, a not-yet-issued delivery note, an already-existing invoice, invoice state legality, invoice issuance for a claim, claim state legality, sample release, retest limit, off-spec finding, measurement discrepancy, asset quarantine, asset state legality, open spill incident, and spill incident state.
9. Segregation of duties — `ERR_SEGREGATION_OF_DUTIES`.
10. Business-safety rules, in this internal order: emission-control sulfur, emission-control documentation, boom certification, grade compatibility, containment confirmation.
11. Referential suitability of a chosen asset — `ERR_ASSET_NOT_SUITABLE`.
12. Temporal rules, in this internal order: nomination window length, slot inside the window, asset slot conflict, port capacity, notice period, claim window, sample retention.
13. Quantitative and uniqueness constraints, in this internal order: asset capacity, affected quantity against basis, measurement figure consistency, duplicate reference code, duplicate delivery note number, duplicate sample seal, empty eligible-asset pool, index quote availability.
14. Fiscal gates last: credit hold, then credit limit.

Placing the fiscal gates last matters commercially: a customer on credit hold whose nomination is also badly documented sees the documentation failure first, because that is the defect the operator can actually fix.

Several of the state guards in step 8 are shared across many operations, and their scope is exhaustive rather than illustrative. The delivery order's `logistics_status` legality check guards nine operations, each rejecting with `ERR_INVALID_ORDER_STATE`: recording clearance, starting pumping, completing pumping, filing a joint survey, cancelling the order, issuing a bunker delivery note, raising an invoice, issuing an invoice, and reporting a spill incident. The order's `measurement_status` legality check guards two operations with `ERR_INVALID_MEASUREMENT_STATE`: filing a joint survey and submitting a quantity decision. The requirement that a governing quantity exist — `measurement_status` of `AGREED` with a non-null `agreed_quantity_mt` — guards three operations with `ERR_MEASUREMENT_NOT_AGREED`: issuing a bunker delivery note, raising an invoice, and issuing an invoice. The asset-quarantine check guards three operations with `ERR_ASSET_QUARANTINED`: scheduling a delivery order by hand, recording clearance, and starting pumping; the auto-schedule route raises no such rejection, because there a quarantined asset is simply absent from the candidate pool. And the quality claim's `status` legality check guards four operations with `ERR_INVALID_CLAIM_STATE`: filing a laboratory analysis, submitting a surveyor decision, requesting a retest, and accepting a remediation.

### 2.9. Stale-Version Guards

Two write operations in the system are guarded by optimistic concurrency control, because in both cases a second write would otherwise succeed against apparently valid state and silently discard work the requester never observed.

Scheduling a delivery order against a nomination — whether the asset and slot are chosen explicitly or derived by the server's auto-schedule capability — requires the non-optional input field `expected_nomination_version`, carrying the client's last observed `version` of the target `Nomination`. If that value does not equal the nomination's current `version`, the request is rejected with `ERR_STALE_NOMINATION_VERSION` (HTTP 412). This guard exists because a new order legitimately supersedes the nomination's existing scheduled or cleared order by cancelling it; without the guard, a client working from a stale read would silently cancel a slot it had never seen.

Filing a laboratory analysis against a quality claim requires the non-optional input field `expected_claim_version`, carrying the client's last observed `version` of the target `QualityClaim`. A mismatch with the claim's current `version` is rejected with `ERR_STALE_CLAIM_VERSION` (HTTP 412). A retest round legitimately supersedes the previous round's verdict as the basis for the remediation decision, so a filing made from a stale read would otherwise overwrite a governing verdict the requester had not read.

No other endpoint accepts a version field, and no other endpoint performs a version comparison.

### 2.10. Measurement, Money and Rounding Discipline

Quantities of fuel are expressed in metric tonnes and carry three decimal places; every tonnage field — `nominated_quantity_mt`, `planned_quantity_mt`, `capacity_mt`, `committed_quantity_mt`, `barge_sounding_mt`, `vessel_sounding_mt`, `meter_mt`, `surveyed_mt`, `agreed_quantity_mt`, `shortfall_mt`, `delivered_quantity_mt`, `affected_quantity_mt`, `quantity_basis_mt` — is rounded to three decimal places using round-half-up.

Monetary amounts are expressed in US dollars and carry two decimal places, likewise round-half-up. Sulfur contents (`max_sulfur_pct`, `eca_sulfur_limit_pct`, `test_tolerance_pct`, `declared_sulfur_pct`, `measured_sulfur_pct`, `exceedance_pct`) carry three decimal places. Two derived figures deviate from the two-decimal money default and are called out where they arise: the bunker adjustment factor `baf_pct` carries four decimal places, and credit utilisation is computed to four decimal places before it is compared with a threshold.

One rounding rule is more consequential than the rest and is repeated in §3.8 because implementers routinely get it wrong: where a total is described as the sum of named components, **each component is rounded to two decimal places first and the already-rounded components are then added**. Summing unrounded components and rounding once at the end is forbidden and produces a different cent.

### 2.11. Emission Control Area Compliance

A `Port` declares through `eca_zone` whether it lies inside an Emission Control Area, and if it does, `eca_sulfur_limit_pct` states the regulatory maximum sulfur content, in mass percent, that the port enforces; the field defaults to a limit of 0.100 mass percent and must be strictly greater than zero. A `FuelGrade` declares `eca_permitted`, whether the grade may lawfully be burned inside such an area, and `max_sulfur_pct`, the contractual sulfur ceiling of the grade as sold.

The regulatory posture of a stem depends on both the port and the vessel. A vessel with an approved exhaust gas cleaning system, flagged by `scrubber_fitted`, may burn a higher-sulfur grade inside an Emission Control Area because its exhaust is scrubbed; a vessel without one may not. Consequently the emission-control checks bite only when the delivery port is inside an Emission Control Area **and** the receiving vessel has no scrubber fitted. Outside that combination, only the grade's own contractual ceiling constrains the stem.

### 2.12. Index Quote Selection

Prices enter the system as immutable `IndexQuote` records, each naming the grade it prices through `grade_id`, the instant it becomes effective through `quote_date`, its `price_usd_per_mt`, and its publishing agency through `source`, which is either `PLATTS` or `ARGUS` and defaults to `PLATTS`. Each `FuelGrade` also names the price index symbol it trades against through `index_code`.

Whenever the system needs the governing price of a grade at a given instant, it selects the quote for that grade whose `quote_date` is the greatest value at or before that instant. When two such quotes share the same `quote_date`, the one with the later `created_at` wins, and when their `created_at` coincides too — as the logical clock makes likely — the one posted later in the server's sequence of writes wins; the most recently posted quote governs. If no quote for that grade exists at or before the instant, the operation is rejected with `ERR_INDEX_QUOTE_UNAVAILABLE` (HTTP 422); this can surface when raising an invoice, when confirming a stem, and when reading a customer's credit exposure.

## 3. Business Logic & Workflows

### 3.1. Reference Data: Ports, Grades, Price Indexation and the Delivery Fleet

Before any stem can be taken, the operations desk populates the supplier's reference data. A port is registered with an operational `port_code` used on clearance paperwork — between 1 and 16 characters, unique across all ports, with a collision rejected as `ERR_DUPLICATE_REFERENCE_CODE` — and a human-readable `name`. Its emission-control profile is optional at registration: `eca_zone` defaults to false and `eca_sulfur_limit_pct` to 0.100 mass percent, recorded to three decimal places and required to be strictly greater than zero. Two logistics parameters complete the record. `notice_lead_hours` is the minimum number of hours that must elapse between now and the start of any delivery slot at the port, and defaults to a full day, that is 24 hours; it may be zero but never negative. `concurrent_ops_capacity` caps how many delivery orders may hold overlapping slots at the port simultaneously and defaults to 2, with a floor of 1. Finally `spill_response_tier` records the port's contracted response capability as `TIER_1`, `TIER_2` or `TIER_3`, defaulting to `TIER_2`.

A fuel grade is registered with a `grade_code` such as MGO-DMA or VLSFO-RME, unique across grades and likewise rejected with `ERR_DUPLICATE_REFERENCE_CODE` on collision, together with its contractual `max_sulfur_pct` ceiling to three decimal places and strictly positive. `eca_permitted` defaults to false. `test_tolerance_pct` captures the ISO 4259 reproducibility tolerance in mass percent that a laboratory result is allowed to exceed the effective limit by before the fuel counts as off-spec; it defaults to 0.010 mass percent, is recorded to three decimals and may be zero but never negative. Commercially, `index_code` names the price index symbol the grade trades against, `base_barging_rate_usd_per_mt` gives the barging or trucking rate in dollars per metric tonne and `min_barging_fee_usd` the floor applied to the resulting fee, both to two decimals and both non-negative; `index_code` and both commercial figures are mandatory at registration. `cross_contamination_group` places the grade in a segregation family — `DISTILLATE`, `RESIDUAL` or `BIOBLEND` — which later determines whether a barge that last carried something else needs segregated tanks.

Index quotes are posted by either the operations desk or the credit desk and are never amended once written; a correction is made by posting a later quote, which is why ties on `quote_date` resolve in favour of the most recently created record as described in §2.12. The quotes for a single grade may be listed on their own, newest `quote_date` first, which is how a credit controller reconstructs the volatility history behind a bunker adjustment factor.

Delivery capacity is registered as assets. Each asset has a `name`, an `asset_type` of either `BARGE` or `TRUCK` declaring the delivery mode it provides, a `capacity_mt` giving the maximum tonnage it can lift in one delivery to three decimals and strictly positive, and a `home_port_id` naming the only port at which it may be scheduled. Three readiness attributes default to conservative values: `boom_certified`, true only when the asset carries a certified containment boom, defaults to false; `segregated_tanks`, true when the asset can load a different cross-contamination family than its last cargo, defaults to false; and `turnaround_buffer_minutes`, the cleaning and transit time the asset needs strictly between two of its own delivery slots, defaults to 90 minutes and may be zero but never negative.

Four fields on an asset are maintained by the system rather than supplied. `last_grade_id` records the grade of the most recent delivery order on that asset that reached pumping, and is null before the asset's first transfer. `status` is `AVAILABLE` on registration and becomes `QUARANTINED` only through the major-spill cascade described in §3.6. `committed_quantity_mt` is the sum of `planned_quantity_mt` across the asset's delivery orders whose `logistics_status` is `SCHEDULED`, `CLEARED` or `PUMPING`, held to three decimals and initialised to 0.000; it is recomputed whenever an order enters or leaves that set. `compliance_score` is initialised to 100.00 and is the asset's spill-history score, computed as described in §3.6.

Assets may be listed and filtered by `home_port_id`, by `last_grade_id`, by `status` or by `asset_type`, which is how the operations desk finds a compatible barge before scheduling by hand.

### 3.2. Buyers, Credit Terms and Exposure Control

A buyer — shipowner, operator or charterer — is onboarded by the credit desk with a `name`, a `credit_limit_usd` giving the maximum settled-plus-committed exposure the supplier will carry, to two decimals and non-negative, and two contractual terms. `payment_terms_days` is the net payment period in days added to an invoice's issuance instant to derive its due date; it defaults to 30 and may be zero but never negative. `settlement_basis` records the contractual quantity basis and is either `SUPPLIER_FIGURES`, the default, or `JOINT_SURVEY_MANDATORY`, which forces an independent surveyor's figure before a delivery note may be issued. On creation, `credit_status` is initialised to `OK` and `outstanding_balance_usd` to 0.00. Both terms may later be revised by a periodic credit review, which accepts an optional replacement `credit_limit_usd`, an optional replacement `settlement_basis`, re-derives the customer's credit standing from settled receivables — rewriting `outstanding_balance_usd` to the settled figure, re-deriving `credit_status` from it and refreshing `available_credit_usd` against the already-stored `conservative_exposure_usd`, while leaving `conservative_exposure_usd` and `open_commitment_count` exactly as they stood — and increments the customer's `version` by one.

Exposure is reported on the customer record through five computed fields, and the same calculation produces all of them in two variants. The **settled receivables** figure is the sum, rounded to two decimal places, of `final_amount_usd` across every invoice belonging to the customer whose status is `ISSUED` or `CREDIT_APPLIED`; invoices that are still `PROVISIONAL` and invoices that have been made `VOID` are excluded entirely. That figure is written to `outstanding_balance_usd` — the backward-looking books view, which counts only money actually invoiced, so a customer holding large unbilled stems still reads a comfortable standing.

The **open commitments** figure adds the stems the supplier has committed to but not yet billed. Its input set is the customer's nominations whose `fulfillment_status` is `CONFIRMED`, `SCHEDULED`, `AWAITING_SCHEDULE` or `DELIVERED` and for which no delivery order carries an invoice in status `ISSUED` or `CREDIT_APPLIED`; nominations still in `DRAFT` and nominations already `CLOSED` are excluded. Each qualifying nomination is valued at its `nominated_quantity_mt` multiplied by the governing index price of its grade at the current logical clock, and the sum is rounded to two decimal places. `open_commitment_count` reports how many nominations entered that set, and defaults to 0.

The **conservative exposure** written to `conservative_exposure_usd` is the settled receivables plus the open commitments, rounded to two decimal places; because it adds unbilled commitments on top of invoiced money, it is strictly larger than the settled figure whenever an unbilled confirmed stem exists. `available_credit_usd` is the customer's `credit_limit_usd` minus that conservative exposure, rounded to two decimal places, and is permitted to be negative. `conservative_exposure_usd` defaults to 0.00, so a freshly onboarded customer with no exposure at all opens with `available_credit_usd` equal to its full `credit_limit_usd`.

Credit standing, however, is derived from the **settled** figure alone, not the conservative one. Utilisation is the settled receivables divided by `credit_limit_usd`, rounded to four decimal places. When utilisation is at least 1.0000 the `credit_status` becomes `HOLD`; when it is at least 0.8000 but below 1.0000 it becomes `WATCH`; otherwise it is `OK`. A `credit_limit_usd` of 0.00 admits no utilisation at all, and the standing is then `HOLD` when any settled receivable exists and `OK` when none does. The exposure figures are recomputed whenever an invoice is issued, whenever an invoice is voided, whenever a remediation credit is booked against an invoice, and on every read of the customer's credit-exposure projection — that read is a computed read and rewrites all five fields before returning them, without refreshing `updated_at` or incrementing `version`, whereas the plain customer read returns the stored projection untouched and recomputes nothing. On the three cascade recomputes a qualifying nomination whose grade has no governing quote is silently left out of the open-commitment set; only the credit-exposure read treats that gap as `ERR_INDEX_QUOTE_UNAVAILABLE`.

A customer whose standing is `HOLD` cannot have a stem confirmed and cannot have a delivery slot cleared: both attempts are rejected with `ERR_CUSTOMER_CREDIT_HOLD` (HTTP 402). A `CustomerRep` may read its own credit exposure but no other customer's.

### 3.3. Nomination Intake and Emission-Control Compliance

A stem enters the system as a **nomination**, submitted either by the operations desk or by the buyer's own representative. The payload identifies the buyer through `customer_id`, the delivery port through `port_id` and the nominated grade through `grade_id`. It describes the receiving vessel through `vessel_imo`, which must be exactly seven digits, and `vessel_name`, and declares whether the vessel has an approved exhaust gas cleaning system through `scrubber_fitted`, which defaults to false. Commercially it states `nominated_quantity_mt`, the tonnage requested, to three decimals and strictly positive, and `declared_sulfur_pct`, the maximum sulfur content in mass percent the customer will accept, to three decimals and strictly positive. Operationally it states `delivery_mode`, either `BARGE` or `TRUCK`, and the delivery window as `window_start`, the earliest instant the vessel can receive bunkers, and `window_end`, the latest. The window must be at least six hours wide: `window_end` must be no earlier than `window_start` plus six hours, and a shorter window is rejected with `ERR_WINDOW_TOO_SHORT`. Finally `eca_documentation_ref` carries the fuel-changeover and bunker-documentation reference; it defaults to null and is only mandatory in the circumstance described below.

On intake the nomination's two dimensions are initialised independently: `fulfillment_status` to `DRAFT` and `compliance_status` to `PENDING_REVIEW`, with `compliance_reviewer_user_id` null.

Regulatory review is the exclusive province of the compliance desk, which submits a `decision` of `APPROVE`, `REJECT` or `REOPEN`. Approving moves `compliance_status` from `PENDING_REVIEW` to `APPROVED` and is gated by three substantive checks. When the delivery port lies inside an Emission Control Area and the vessel has no scrubber fitted, the nominated grade must be flagged as permitted inside such an area and its contractual sulfur ceiling must be no greater than the port's enforced limit; otherwise the review is rejected with `ERR_ECA_SULFUR_VIOLATION`. In that same circumstance the nomination's `eca_documentation_ref` must not be null, or the review is rejected with `ERR_ECA_DOCUMENTATION_MISSING`. Independently of the port, and in all cases, the customer's `declared_sulfur_pct` must be no greater than the grade's `max_sulfur_pct`, and a stem that declares a tighter requirement than the grade can meet is also rejected with `ERR_ECA_SULFUR_VIOLATION`; that third check is evaluated last of the three, so a stem inside an Emission Control Area that is both undocumented and tighter than its grade reports `ERR_ECA_DOCUMENTATION_MISSING`. A successful approval records the reviewing officer's `X-User-ID` as `compliance_reviewer_user_id` and increments the nomination's `version` by one.

Rejecting a stem is the mirror action with a single precondition — the nomination must currently be in `PENDING_REVIEW` — and it moves `compliance_status` to `REJECTED`. It, too, records the deciding officer's `X-User-ID` as `compliance_reviewer_user_id` and increments `version` by one; none of the sulfur or documentation checks apply, because rejection is precisely what an operator does when those checks would fail. Reopening runs the cycle backwards: a nomination in `REJECTED` returns to `PENDING_REVIEW` once the customer has amended the stem documentation, but only while `fulfillment_status` is still `DRAFT` — a stem that has already progressed is rejected with `ERR_INVALID_NOMINATION_STATE`. Reopening clears `compliance_reviewer_user_id` back to null and increments `version` by one, so the officer who eventually approves the reopened stem is recorded afresh and remains eligible or ineligible to issue the later delivery note on that basis.

Attempting any of the three decisions from a state that does not permit it is rejected with `ERR_INVALID_NOMINATION_STATE` (HTTP 409). Nominations may be listed and filtered by `customer_id`, `port_id`, `grade_id`, `fulfillment_status` or `compliance_status`, though a `CustomerRep` listing them only ever sees its own.

### 3.4. Stem Confirmation and Slot Scheduling

Confirmation is the commercial commitment, and only the operations desk may make it. It moves `fulfillment_status` from `DRAFT` to `CONFIRMED` and is gated by three conditions in addition to the state check: the nomination's `compliance_status` must already be `APPROVED`, or the request is rejected with `ERR_COMPLIANCE_NOT_APPROVED`; the customer's `credit_status` must not be `HOLD`, or the request is rejected with `ERR_CUSTOMER_CREDIT_HOLD`; and the conservative credit check must pass, or the request is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402). Confirmation increments the nomination's `version` by one and brings the stem into the open-commitment set that inflates the customer's conservative exposure.

The **conservative credit check** works as follows. The prospective commitment of the addressed nomination is its `nominated_quantity_mt` multiplied by the governing index price of its grade at the current logical clock, rounded to two decimal places. The prospective exposure is the customer's current conservative exposure plus that prospective commitment, rounded to two decimal places — but the commitment is added only while the nomination is still in `DRAFT`. The check runs at confirmation only: clearing a delivery slot enforces the credit-hold gate alone and never repeats the limit comparison, which is consistent with the stem already sitting inside the conservative exposure by then, so that nothing would be added a second time. The comparison is deliberately generous at the boundary: a prospective exposure exactly equal to `credit_limit_usd` passes, and only an exposure strictly greater than the limit fails.

Once confirmed, a stem needs a slot. The operations desk may schedule by hand, supplying `nomination_id`, `asset_id`, `planned_quantity_mt`, `slot_start`, `slot_end` and `expected_nomination_version`, or delegate to the server's auto-schedule capability, supplying only `requested_slot_start` and `expected_nomination_version`. Either route moves `fulfillment_status` to `SCHEDULED` from either `CONFIRMED` or `AWAITING_SCHEDULE` — any other fulfilment state is rejected with `ERR_INVALID_NOMINATION_STATE` — creates a `DeliveryOrder` with `logistics_status` `SCHEDULED` and `measurement_status` `NOT_STARTED`, recomputes the chosen asset's `committed_quantity_mt`, and increments the nomination's `version` by one. Scheduling by hand additionally has a supersede effect: any pre-existing delivery order on the same nomination whose `logistics_status` is `SCHEDULED` or `CLEARED` transitions to `CANCELLED`, which in turn recomputes that order's asset's `committed_quantity_mt`. The auto-schedule route cancels an existing scheduled or cleared order on the nomination in the same way. On both routes that cancellation runs only after every admissibility check on the new slot has passed, so the order about to be superseded still counts as a live commitment while the asset-conflict and port-capacity rules are evaluated, and the cancellation does not itself push the nomination to `AWAITING_SCHEDULE`. This supersede behaviour is exactly why both routes require `expected_nomination_version` per §2.9. Re-slotting a stem after a cancellation follows the cycle `SCHEDULED → AWAITING_SCHEDULE → SCHEDULED`, and the replacement order is created by the same two routes.

A hand-scheduled order must name a suitable asset: the asset's `home_port_id` must equal the nomination's `port_id` and the asset's `asset_type` must equal the nomination's `delivery_mode`, or the request is rejected with `ERR_ASSET_NOT_SUITABLE`. The asset must not be `QUARANTINED`, or the request is rejected with `ERR_ASSET_QUARANTINED`. The `planned_quantity_mt` may not exceed the asset's `capacity_mt`, or the request is rejected with `ERR_ASSET_CAPACITY_EXCEEDED`. And the asset must be able to carry the grade: either its `last_grade_id` is null, or the cross-contamination family of the grade it last carried matches the family of the nominated grade, or the asset has `segregated_tanks`; failing all three, the request is rejected with `ERR_GRADE_INCOMPATIBLE_ASSET`.

Four temporal rules govern any slot, whichever route created it. The slot must sit fully inside the nomination's window — `slot_start` no earlier than `window_start` and `slot_end` no later than `window_end` — or the request is rejected with `ERR_SLOT_OUTSIDE_WINDOW`. The slot must respect the port's notice period: `slot_start` must be no earlier than the current logical clock plus the port's `notice_lead_hours`, or the request is rejected with `ERR_NOTICE_PERIOD_MISSED`. The slot must not collide with the asset's own commitments: taking every **other** delivery order on the same asset whose `logistics_status` is `SCHEDULED`, `CLEARED` or `PUMPING`, the new closed interval from `slot_start` through `slot_end` must not intersect the existing closed interval, and the gap between the two intervals must be strictly greater than the asset's `turnaround_buffer_minutes` — a gap exactly equal to the buffer is rejected, not accepted. A violation of either half of that rule is reported as `ERR_ASSET_SLOT_CONFLICT` (HTTP 409). Finally the port's own throughput is capped: counting the delivery orders at the same port whose `logistics_status` is `SCHEDULED`, `CLEARED` or `PUMPING` and whose half-open interval from `slot_start` up to but excluding `slot_end` intersects the new order's half-open interval, the new order is rejected with `ERR_PORT_CAPACITY_EXCEEDED` (HTTP 409) when that count already equals or exceeds the port's `concurrent_ops_capacity`. Because the port rule uses half-open intervals, two back-to-back slots that merely touch at an endpoint do not intersect and are always allowed — a deliberate asymmetry with the asset rule, which uses closed intervals and therefore treats a shared endpoint as an overlap.

**Server-side asset selection.** When the operations desk delegates, the server builds a candidate pool from the delivery assets satisfying every one of the following: the asset's `home_port_id` equals the nomination's `port_id`; the asset's `asset_type` equals the nomination's `delivery_mode`; the asset's `status` is `AVAILABLE`; the asset's `capacity_mt` is at least the nomination's `nominated_quantity_mt`; the asset is `boom_certified`; the asset's `last_grade_id` is null, or shares the nominated grade's cross-contamination family, or the asset has `segregated_tanks`; the asset has no spill incident in status `OPEN`; and the derived slot does not violate the asset-level buffer rule described above. The port-level capacity rule does not depend on which asset is chosen, so on this route it is evaluated once as a standalone precondition before the pool is built — after the slot-inside-window check and before the notice-period check — and a saturated port is therefore reported as `ERR_PORT_CAPACITY_EXCEEDED` rather than as an empty pool. Surviving candidates are ranked by `compliance_score` in descending order; ties are broken by the tightest fit, meaning the smallest value of the asset's `capacity_mt` minus the nomination's `nominated_quantity_mt`, in ascending order; any remaining tie is broken by `created_at` in ascending order. The first candidate in that ranking is chosen. If the pool is empty, the request is rejected with `ERR_NO_ELIGIBLE_ASSET` (HTTP 409).

The slot itself is derived rather than supplied on this route. `slot_start` is taken from `requested_slot_start`. The pumping duration in minutes is the nomination's `nominated_quantity_mt` divided by a pumping rate of 250 metric tonnes per hour, converted to minutes by multiplying by 60, and rounded **up** to a whole minute. `slot_end` is `slot_start` plus that pumping duration plus a fixed hose connection and disconnection allowance of 60 minutes. `planned_quantity_mt` on the created order defaults to the nomination's `nominated_quantity_mt`, carried at three decimal places.

### 3.5. Clearance, Pumping and Quantity Reconciliation

A scheduled order becomes operational once port authority and terminal clearance are recorded. The operations desk supplies a `port_clearance_ref`, and the order advances `SCHEDULED → CLEARED`, storing that reference and stamping `cleared_at` with the current logical clock. Clearance is gated by four substantive conditions beyond the state check: the nomination's `compliance_status` must be `APPROVED`, else `ERR_COMPLIANCE_NOT_APPROVED`; the asset's `status` must be `AVAILABLE`, else `ERR_ASSET_QUARANTINED`; no spill incident on that asset may still be `OPEN`, else `ERR_OPEN_SPILL_INCIDENT`; and the customer's `credit_status` must not be `HOLD`, else `ERR_CUSTOMER_CREDIT_HOLD`.

The barge master then starts the transfer, advancing the order `CLEARED → PUMPING`. Three safety conditions are enforced at exactly this moment and nowhere else. The asset must be `boom_certified`, because the spill prevention plan cannot otherwise be satisfied — a non-certified asset is rejected with `ERR_BOOM_NOT_CERTIFIED`. The grade segregation rule is re-checked against live state: the asset's `last_grade_id` must be null, or the family of the grade it last carried must match the family of the nominated grade, or the asset must have `segregated_tanks`, else the start is rejected with `ERR_GRADE_INCOMPATIBLE_ASSET`. And the slot must actually have begun: the logical clock must be at or after the order's `slot_start`, else the start is rejected with `ERR_SLOT_OUTSIDE_WINDOW`. A successful start writes the nomination's grade onto the asset as its `last_grade_id`, which is what makes the segregation rule bite on the asset's next stem.

Completing the transfer is where measurement begins. The barge master submits three figures: `barge_sounding_mt`, the supplier-side tank sounding; `vessel_sounding_mt`, the receiving vessel's own tank sounding; and `meter_mt`, the mass-flow meter totaliser. Two constraints are enforced before the transfer may close. The barge sounding and the meter totaliser must agree within a tolerance of one tonne — the absolute difference between `barge_sounding_mt` and `meter_mt` must be no greater than 1.000 metric tonnes — or the request is rejected with `ERR_MEASUREMENT_FIGURES_INCONSISTENT`. And `barge_sounding_mt` may not exceed the asset's `capacity_mt`, or the request is rejected with `ERR_ASSET_CAPACITY_EXCEEDED`.

A successful completion does a great deal at once. The order advances `PUMPING → DELIVERED` on its logistics dimension and `NOT_STARTED → FIGURES_RECORDED` on its measurement dimension, storing all three figures. The order leaves the asset's committed set, so `committed_quantity_mt` is recomputed. The asset's `compliance_score` is recomputed, because a delivered order with no spill against it earns the clean-delivery bonus described in §3.6. And the nomination cascades `SCHEDULED → DELIVERED` on its fulfilment dimension.

From `FIGURES_RECORDED` the measurement dimension forks, and which branch is taken is dictated by the customer's contract, never chosen freely. **On the supplier-figures branch** — taken when the customer's `settlement_basis` is `SUPPLIER_FIGURES` — the measurement dimension advances `FIGURES_RECORDED → AGREED` inside the very same completion request. The supplier's own barge tank sounding governs: `agreed_quantity_mt` is `barge_sounding_mt` rounded to three decimal places, `measurement_basis` is set to `SUPPLIER_FIGURES`, and `shortfall_mt` is 0.000, because the governing figure and the pumped figure are one and the same. The customer is billed the full pumped tonnage.

**On the joint-survey branch** — mandatory when the customer's `settlement_basis` is `JOINT_SURVEY_MANDATORY` — the completion request leaves the order in `FIGURES_RECORDED` awaiting an independent figure, and `agreed_quantity_mt`, `measurement_basis` and `shortfall_mt` all stay null. A `Surveyor` then files `surveyed_mt`, advancing the measurement dimension to `RESURVEYED`; that filing requires the order's `logistics_status` to be `DELIVERED` and its `measurement_status` to be either `FIGURES_RECORDED` or `DISPUTED`, and an illegal measurement state is rejected with `ERR_INVALID_MEASUREMENT_STATE` (HTTP 409). The surveyor then closes the loop with a quantity `decision` of `AGREE`, advancing `RESURVEYED → AGREED` provided `surveyed_mt` is not null: the surveyor's figure governs, so `agreed_quantity_mt` is `surveyed_mt` rounded to three decimal places, `measurement_basis` is set to `JOINT_SURVEY`, and `shortfall_mt` is `barge_sounding_mt` minus `agreed_quantity_mt`, rounded to three decimal places — normally a positive difference the supplier absorbs.

Two figures never govern the settled tonnage, and it is worth saying so plainly. `meter_mt` exists only to police the barge sounding through the one-tonne cross-check at completion. `vessel_sounding_mt` exists only to establish the customer's right to dispute.

That dispute right is exercised by the buyer's representative through a quantity `decision` of `DISPUTE`, which moves the measurement dimension `AGREED → DISPUTED` and clears `agreed_quantity_mt`, `measurement_basis` and `shortfall_mt` back to null. Two conditions guard it. No bunker delivery note in status `ISSUED` may exist for the order, because a note already fixes the delivered figure on MARPOL paperwork — an attempt after issuance is rejected with `ERR_BDN_ALREADY_ISSUED`. And the customer must actually have evidence of a shortfall: `vessel_sounding_mt` must be strictly less than `barge_sounding_mt`, or the dispute is rejected with `ERR_NO_MEASUREMENT_DISCREPANCY`. A disputed order returns to `RESURVEYED` when the surveyor files a fresh `surveyed_mt`, which overwrites the previous survey figure, and the cycle `AGREED → DISPUTED → RESURVEYED → AGREED` closes when the surveyor agrees the resurveyed figure on the joint-survey basis. Although the quantity-decision endpoint admits both desks, each branch belongs to exactly one of them: once the payload has been validated, a `Surveyor` submitting `DISPUTE` or a `CustomerRep` submitting `AGREE` is rejected with `ERR_ROLE_NOT_PERMITTED`.

Cancellation exists for orders that never deliver. The operations desk may cancel an order whose `logistics_status` is `SCHEDULED`, `CLEARED` or `SUSPENDED`, moving it to `CANCELLED`; any other state is rejected with `ERR_INVALID_ORDER_STATE` (HTTP 409). Cancellation always recomputes the asset's `committed_quantity_mt`, releasing the order's `planned_quantity_mt`. Cancelling an order that is still `CLEARED` at the moment of cancellation additionally compensates the clearance by clearing `port_clearance_ref` and `cleared_at` back to null; an order cancelled out of `SUSPENDED` keeps whatever clearance reference it was carrying. And in every case, when no other non-terminal delivery order remains on the nomination — that is, when none of its orders is any longer in `SCHEDULED`, `CLEARED` or `PUMPING` — the nomination cascades `SCHEDULED → AWAITING_SCHEDULE`, incrementing its `version`, so the stem can be re-slotted. Delivery orders may be listed and filtered by `nomination_id`, by `asset_id`, by `logistics_status` or by `measurement_status`.

### 3.6. Spill Prevention, Containment and Asset Quarantine

A spill during a transfer is reported by the barge master against the delivery order it happened on, naming `delivery_order_id`, the `reported_at` instant the spill was observed, the estimated `volume_liters` to two decimals and strictly positive, and `boom_deployed`, recording whether the containment boom was in the water before pumping resumed. The system copies `asset_id` from the delivery order and `port_id` from the nomination behind it, so the incident is attributable without the reporter having to restate either.

The incident's `severity` is derived, not declared: it is `MAJOR` when the spilled volume is at least 100.00 litres **or** the boom was not deployed, and `MINOR` otherwise. That `severity` fixes `penalty_points`: 45.00 points for a major incident, 15.00 for a minor one. The incident opens in status `OPEN` with `containment_confirmed` false, `response_ref` null and `closed_at` null.

Reporting an incident always suspends the delivery it happened on: an order in `SCHEDULED`, `CLEARED` or `PUMPING` moves to `SUSPENDED`, and the asset's `compliance_score` and `committed_quantity_mt` are recomputed, the former to absorb the new penalty points. The suspended order's own nomination is left exactly as it stands, keeping its `SCHEDULED` fulfilment standing. When and only when the derived severity is `MAJOR`, a deeper cascade fires: the asset moves `AVAILABLE → QUARANTINED`, an asset already quarantined simply staying so without any rejection; every **other** delivery order on that asset whose `logistics_status` is `SCHEDULED` or `CLEARED` moves to `CANCELLED`; and each of those cancelled orders pushes its own nomination `SCHEDULED → AWAITING_SCHEDULE`. Each cancellation also recomputes the asset's `committed_quantity_mt`. A minor incident suspends only its own order and leaves the asset available.

Containment is signed off by the compliance desk in two steps. First, confirming containment records the port response team's case reference as `response_ref` and sets `containment_confirmed` to true; nothing else sets that flag. That step carries no state guard of its own: it may be repeated, overwriting `response_ref`, and it is accepted even against an incident already `CLOSED`. Second, closing the incident moves it `OPEN → CLOSED` and stamps `closed_at` with the logical clock, but only if `containment_confirmed` is true and `response_ref` is not null — either omission is rejected with `ERR_CONTAINMENT_NOT_CONFIRMED` (HTTP 422). Closing an incident that is already `CLOSED` is rejected with `ERR_INVALID_SPILL_STATE` (HTTP 409).

Releasing a quarantined asset back into service is likewise the compliance desk's call, moving `status` `QUARANTINED → AVAILABLE`. The asset must actually be quarantined — a request against an already-available asset is rejected with `ERR_INVALID_ASSET_STATE` — and no spill incident on the asset may remain `OPEN`, else the request is rejected with `ERR_OPEN_SPILL_INCIDENT`. Release recomputes the asset's `compliance_score` against the current decay window, so the asset re-enters the auto-schedule candidate pool with a score that reflects how long ago its incidents happened. Incidents may be listed and filtered by `delivery_order_id`, `asset_id`, `port_id` or `status`.

**The compliance score.** An asset's score is recomputed whenever a spill incident is reported, whenever a delivery completes pumping, and whenever a quarantine is lifted. It begins from a perfect 100.00 and is adjusted by a penalty term and a bonus term.

The penalty term walks every spill incident recorded against the asset, regardless of whether the incident is still `OPEN` or already `CLOSED`, taking them in ascending order of `reported_at` and, where two incidents share that instant, in ascending order of `created_at`. For each incident, its age in whole days is the elapsed time from `reported_at` to the current logical clock divided by 24 hours and rounded down to a whole number of days. An incident aged 30 days or fewer contributes its full `penalty_points`, weighted by 1.00. An incident aged 31 through 90 days contributes half, weighted by 0.50. An incident aged 91 through 180 days contributes a quarter, weighted by 0.25. An incident older than 180 days contributes nothing and is excluded. Each incident's weighted contribution is rounded to two decimal places before it is added to the running penalty.

The bonus term rewards clean work. The system counts the delivery orders on the asset whose `logistics_status` is `DELIVERED` and against which no spill incident was ever recorded. Each such delivery earns 1.00 point, the total is rounded to two decimal places, and the bonus is capped at 10.00 points however many clean deliveries the asset has accumulated.

The score is then 100.00 minus the accumulated penalty plus the bonus, rounded to two decimal places, and finally clamped into the inclusive range from 0.00 to 100.00. Because the penalty decays with age while the bonus accrues with clean deliveries, an asset that spilled six months ago and has run twenty clean stems since ranks above an asset that spilled last week — which is precisely the ranking the server-side selector in §3.4 consumes.

### 3.7. Delivery Notes, Retained Samples and Quality Claims

The MARPOL bunker delivery note is the legal evidence of what was delivered, and it may only be issued once the tonnage is settled. The operations desk issues it against `delivery_order_id`, supplying `bdn_number`, the MARPOL Annex VI note number, `declared_sulfur_pct`, the sulfur content in mass percent the supplier declares on the note to three decimals and strictly positive, and `sample_seal_number`, the seal number of the mandatory retained sample. Both `bdn_number` and `sample_seal_number` are unique across all notes, and collisions are rejected with `ERR_DUPLICATE_BDN_NUMBER` and `ERR_DUPLICATE_SAMPLE_SEAL` respectively (both HTTP 409). Issuance requires the order's `logistics_status` to be `DELIVERED`, or the request is rejected with `ERR_INVALID_ORDER_STATE`, and its `measurement_status` to be `AGREED` with a non-null `agreed_quantity_mt`, or the request is rejected with `ERR_MEASUREMENT_NOT_AGREED` (HTTP 409) — which is how the `JOINT_SURVEY_MANDATORY` settlement basis makes a surveyor's figure a precondition of paperwork. The segregation-of-duties rule of §2.1 also applies here: the issuing coordinator's `X-User-ID` is stored as `issued_by_user_id` and must differ from the `compliance_reviewer_user_id` on the nomination behind the order.

A newly issued note snapshots `delivered_quantity_mt` from the order's `agreed_quantity_mt` at the moment of issuance, sets `status` to `ISSUED`, and starts the sample custody clock: `sample_retention_until` is the note's `created_at` plus a 90-day retention period, `sample_custody_status` begins as `RETAINED`, and `sample_released_at` is null. Issuing a corrected note against the same delivery order supersedes the earlier one: the prior note transitions `ISSUED → SUPERSEDED`, provided no quality claim references it — a note a claim already references stays `ISSUED` alongside the new one. A claim names its note through `bdn_id` and that note's `status` is not re-examined at submission, so a superseded note may still be claimed against.

Sample custody is derived on every read rather than stored as an independent fact. If `sample_released_at` is set, `sample_custody_status` reads `RELEASED_TO_LAB`; otherwise, if the logical clock is past `sample_retention_until`, it reads `EXPIRED`; otherwise it reads `RETAINED`. The operations desk releases a sample to the laboratory by stamping `sample_released_at` with the logical clock, which flips the derived custody status. A release attempted after the retention period has lapsed — that is, when the logical clock is past `sample_retention_until`, so custody already reads `EXPIRED` — is rejected with `ERR_SAMPLE_RETENTION_EXPIRED` (HTTP 422), because a sample outside its retention window can no longer back a claim. That lapse is the only gate on a release: the note's own `status` is never examined, and releasing an already-released sample simply restamps `sample_released_at` with the current clock. Notes may be listed and filtered by `delivery_order_id` or by `status`, and both the single read and the list re-derive custody against the current clock.

A **quality claim** is raised by the buyer's representative against the note whose retained sample will be tested, naming `bdn_id`, the `claimed_defect` — one of `SULFUR_EXCEEDANCE`, `WATER_CONTENT` or `DENSITY_DEVIATION` — and the `affected_quantity_mt` the customer says is unusable, to three decimals and strictly positive. `replacement_price_usd_per_mt`, the price the customer paid for replacement fuel, is optional at submission and defaults to null, and when supplied is carried to two decimals and must be strictly positive; it becomes mandatory only on the debunkering remediation branch described in §3.8. Two temporal and quantitative gates apply. The claim must be raised inside a 30-day window: the logical clock must be no later than the note's `created_at` plus 30 days, or the claim is rejected with `ERR_CLAIM_WINDOW_CLOSED` (HTTP 422). And `affected_quantity_mt` may not exceed the note's `delivered_quantity_mt`, or the claim is rejected with `ERR_AFFECTED_QUANTITY_EXCEEDS_BASIS` (HTTP 422).

On submission the claim snapshots `quantity_basis_mt` from the note's `delivered_quantity_mt` and copies `customer_id` from the nomination behind the note; that snapshot is taken once and never re-read, so a later corrected note cannot retroactively move the basis of a claim already in flight. `status` is initialised to `SUBMITTED`, `analysis_round` to 0, `credit_usd` to 0.00, and `remediation_type`, `proposed_by_user_id` and `accepted_by_user_id` to null. Claims may be listed and filtered by `bdn_id`, by `customer_id` or by `status`, subject to the customer scope rule.

### 3.8. Laboratory Analysis, Remediation and Settlement

Testing is the laboratory's work. A `LabTechnician` files an analysis against `claim_id`, supplying `lab_ref`, the laboratory report reference, `measured_sulfur_pct`, the sulfur content in mass percent measured on the retained sample to three decimals and strictly positive, and `expected_claim_version` per §2.9. A retest additionally carries `retest_of_analysis_id`, naming the first-round analysis being re-examined; on a first round it is omitted and defaults to null. The acting technician's `X-User-ID` is recorded as `analyzed_by_user_id`. Filing is only possible once the note's `sample_custody_status` is `RELEASED_TO_LAB`; a claim whose sample is still retained or already expired is rejected with `ERR_SAMPLE_NOT_RELEASED` (HTTP 409).

Which round a filing constitutes is decided by the presence of `retest_of_analysis_id`, and the state each branch demands differs accordingly. The first filing on a claim carries no `retest_of_analysis_id`, requires the claim to be in `SUBMITTED`, moves it `SUBMITTED → UNDER_ANALYSIS`, sets the analysis's `round_index` to 1 and the claim's `analysis_round` to 1, and increments the claim's `version` by one. A second filing is a self-loop that re-enters `UNDER_ANALYSIS`: it requires the claim to be in `UNDER_ANALYSIS`, requires `analysis_round` to still be below the ceiling of two rounds, and requires `retest_of_analysis_id` to reference an analysis on this same claim whose `round_index` is 1 — an identifier that resolves but belongs to another claim or to another round is rejected with `ERR_INVALID_REQUEST`. It sets the new analysis's `round_index` to 2 and the claim's `analysis_round` to 2 and increments the claim's `version` by one. A third filing has nowhere to go and is rejected with `ERR_RETEST_LIMIT_REACHED` (HTTP 409); the same ceiling and the same error also govern a customer's request for a retest. A filing against a claim in any other status than the one its branch demands — a first round against a claim not in `SUBMITTED`, or a retest against a claim not in `UNDER_ANALYSIS` — is rejected with `ERR_INVALID_CLAIM_STATE` (HTTP 409).

**The off-spec verdict.** Every filed analysis is judged immediately, writing `verdict` and `exceedance_pct`. The regulatory limit that applies is the port's `eca_sulfur_limit_pct` when the delivery port lies inside an Emission Control Area and the receiving vessel has no scrubber fitted; in every other case it is the grade's `max_sulfur_pct`. The effective limit is then the lower of that regulatory limit and the grade's own `max_sulfur_pct`, so contractual and regulatory ceilings are both honoured and the tighter one binds. The trip point is the effective limit plus the grade's `test_tolerance_pct`, the ISO 4259 reproducibility allowance. The `verdict` is `OFF_SPEC` when `measured_sulfur_pct` is strictly greater than that trip point and `ON_SPEC` otherwise — a measurement exactly equal to the trip point is `ON_SPEC`. `exceedance_pct` is `measured_sulfur_pct` minus the trip point, rounded to three decimal places, and floored at 0.000, so an on-spec result always reports an exceedance of 0.000.

**The surveyor's decision.** Once a claim is under analysis, the `Surveyor` submits a `decision` of either `PROPOSE` or `REJECT`, and the governing analysis for that decision is always the one on the claim with the highest `round_index`, the later `created_at` breaking any tie. Proposing moves the claim `UNDER_ANALYSIS → REMEDIATION_PROPOSED` and requires the governing analysis to have verdict `OFF_SPEC`; rejecting moves the claim `UNDER_ANALYSIS → REJECTED` and requires the governing analysis to have verdict `ON_SPEC`. A decision that contradicts the governing verdict in either direction is rejected with `ERR_NO_OFFSPEC_FINDING` (HTTP 409). A proposal names `remediation_type`, either `PRICE_ALLOWANCE` or `DEBUNKER`, and a proposal that omits it is rejected with `ERR_INVALID_REQUEST`; the debunkering branch also requires the claim's `replacement_price_usd_per_mt` to be non-null, and a debunkering proposal without it is rejected with `ERR_INVALID_REQUEST`. Both decisions require a non-void invoice to exist on the claim's delivery order — the most recently created one, should several qualify — or the decision is rejected with `ERR_INVOICE_NOT_ISSUED` (HTTP 409). A proposal records the surveyor's `X-User-ID` as `proposed_by_user_id`, computes `credit_usd`, and increments the claim's `version` by one. A rejection leaves `credit_usd` at 0.00, touches no invoice, and likewise increments the claim's `version` by one.

A buyer who is unhappy with a proposal may push back once. Requesting a retest moves the claim `REMEDIATION_PROPOSED → UNDER_ANALYSIS`, clears `remediation_type` to null, resets `credit_usd` to 0.00, clears `proposed_by_user_id` to null and increments the claim's `version` by one; it too requires `analysis_round` to remain below the two-round ceiling, failing which it is rejected with `ERR_RETEST_LIMIT_REACHED`. That closes the negotiation cycle `UNDER_ANALYSIS → REMEDIATION_PROPOSED → UNDER_ANALYSIS`.

**The remediation credit.** The credit attached to a proposal is computed in a pinned sequence of eight steps, and no step may re-read a later step's output — the cap in step seven derives from the invoice total, which itself derives from the quantity basis the claim snapshotted in step one, so the order is load-bearing. First, the basis tonnage is the claim's `quantity_basis_mt`, the snapshot taken at submission and never re-read from the note. Second, the affected tonnage is the claim's `affected_quantity_mt`, already validated as not exceeding the basis. Third, the reference price is `index_price_usd_per_mt` from the non-void invoice on the claim's delivery order. Fourth, a per-tonne rate is derived from the remediation branch: on the `PRICE_ALLOWANCE` branch it is the reference price multiplied by an off-spec allowance of 15 percent, rounded to two decimal places; on the `DEBUNKER` branch it is the greater of a handling floor of 12.00 dollars per tonne and the quantity formed by taking the claim's `replacement_price_usd_per_mt` minus the reference price, adding 12.00 dollars per tonne of handling, and rounding to two decimal places. Fifth, the raw credit is the affected tonnage multiplied by that rate, rounded to two decimal places. Sixth, severity is escalated: if the governing analysis's `exceedance_pct` is strictly greater than 0.050 mass percent, the raw credit is multiplied by 1.25 and rounded again to two decimal places. Seventh, a cap is computed as the invoice's `provisional_amount_usd` multiplied by 60 percent, rounded to two decimal places. Eighth, `credit_usd` is the lesser of the raw credit and that cap.

**Booking the credit.** The credit desk accepts a proposed remediation, moving the claim `REMEDIATION_PROPOSED → REMEDIATION_ACCEPTED` and recording the acting `X-User-ID` as `accepted_by_user_id`, which must differ from `proposed_by_user_id` per the segregation rule of §2.1. Acceptance requires the invoice on the claim's delivery order to be in status `ISSUED`, or it is rejected with `ERR_INVOICE_NOT_ISSUED`. Acceptance books `credit_usd` and cascades three levels deep: the invoice's `claim_credit_usd` is increased by the claim's `credit_usd`, its `final_amount_usd` is recomputed, and its `status` moves `ISSUED → CREDIT_APPLIED`; that invoice mutation itself cascades a recompute of the customer's `outstanding_balance_usd`; and that recompute in turn cascades a re-derivation of the customer's `credit_status`.

### 3.9. Invoicing, Indexation and the Bunker Adjustment Factor

Billing is the credit desk's exclusive province. A provisional invoice is raised against `delivery_order_id` with a `pricing_date`, the indexation date that selects the governing quote. The order must be physically `DELIVERED`, or the request is rejected with `ERR_INVALID_ORDER_STATE`; its `measurement_status` must be `AGREED` with a settled `agreed_quantity_mt`, or the request is rejected with `ERR_MEASUREMENT_NOT_AGREED`; and no invoice in status `PROVISIONAL`, `ISSUED` or `CREDIT_APPLIED` may already exist for the order, or the request is rejected with `ERR_INVOICE_ALREADY_EXISTS` (HTTP 409). The invoice copies `customer_id` from the nomination behind the order and opens in status `PROVISIONAL` with `issued_at` and `due_date` null and `claim_credit_usd` at 0.00.

**The invoice amount.** `quantity_basis_mt` snapshots the order's `agreed_quantity_mt`. `index_price_usd_per_mt` is the governing index price of the nomination's grade at the invoice's `pricing_date`, selected exactly as §2.12 prescribes. The invoice then has four components, and the rounding order among them is pinned: each component is rounded to two decimal places **first**, and the four already-rounded components are then added, without a further rounding of the sum.

`fuel_cost_usd` is the quantity basis multiplied by the index price, rounded to two decimal places. `baf_usd` is the **already-rounded** `fuel_cost_usd` multiplied by `baf_pct`, rounded to two decimal places — the adjustment factor applies to the rounded fuel cost, not to the raw product. `barging_fee_usd` is the greater of two values: the quantity basis multiplied by the grade's `base_barging_rate_usd_per_mt` and rounded to two decimal places, or the grade's `min_barging_fee_usd` floor. `eca_surcharge_usd` is the quantity basis multiplied by an emission-control surcharge of 4.25 dollars per metric tonne, rounded to two decimal places, when the delivery port lies inside an Emission Control Area; at any other port it is 0.00. `provisional_amount_usd` is the sum of those four rounded components.

`claim_credit_usd` is the sum, rounded to two decimal places, of `credit_usd` across the quality claims raised against this delivery order's notes whose `status` is `REMEDIATION_ACCEPTED`. `final_amount_usd` is `provisional_amount_usd` minus `claim_credit_usd`, rounded to two decimal places.

**The bunker adjustment factor.** `baf_pct` is derived when the invoice is raised, to four decimal places, and it is the one figure in the system that looks at price history rather than a single quote. The governing quote is the one selected for the invoice's `pricing_date`. The prior quote is the quote for the same grade whose `quote_date` is the greatest value strictly earlier than the governing quote's `quote_date`, with ties again resolved in favour of the later `created_at`. Volatility is the absolute difference between the two quotes' `price_usd_per_mt` divided by the prior quote's `price_usd_per_mt`; when no prior quote exists, volatility is zero.

The factor is then assembled from a base and four adjustments. The base is 0.020. The volatility step contributes 0.000 while volatility is below 0.05, contributes 0.010 once volatility reaches 0.05 but stays below 0.10, and contributes 0.020 once volatility reaches 0.10. The mode premium contributes 0.015 when the nomination's `delivery_mode` is `TRUCK` and 0.005 when it is `BARGE`. The emission-control premium contributes 0.010 when the delivery port lies inside an Emission Control Area and nothing otherwise. A tier discount of 0.010 is **subtracted** when the invoice's `quantity_basis_mt` is at least 1000.000 metric tonnes, and nothing is subtracted below that. The raw factor is the base plus the volatility step plus the mode premium plus the emission-control premium, minus the tier discount. That raw figure is then clamped into the inclusive range from a floor of 0.010 to a ceiling of 0.045 — the clamp is applied first — and only then rounded to four decimal places to give `baf_pct`.

**Issuance and settlement.** Issuing an invoice moves it `PROVISIONAL → ISSUED` and requires three conditions beyond the state check: the order's `logistics_status` must be `DELIVERED`, else `ERR_INVALID_ORDER_STATE`; the order's `measurement_status` must be `AGREED`, else `ERR_MEASUREMENT_NOT_AGREED`; and a bunker delivery note in status `ISSUED` must exist for the order, else `ERR_BDN_NOT_ISSUED` (HTTP 409). Issuance stamps `issued_at` with the logical clock and derives `due_date` as `issued_at` plus the customer's `payment_terms_days` days; it recomputes none of the amount components, which stay as they were derived when the invoice was raised. It then recomputes the customer's `outstanding_balance_usd`, which itself cascades a re-derivation of the customer's `credit_status`, and cascades the nomination `DELIVERED → CLOSED` on its fulfilment dimension.

Voiding is the compensating action, and it is available from three states. Voiding an invoice still in `PROVISIONAL` moves it to `VOID` and touches nothing else — no receivable ever existed, so the customer's `outstanding_balance_usd` is unchanged. Voiding an invoice in `ISSUED` moves it to `VOID`, recomputes the customer's `outstanding_balance_usd` to remove the receivable and re-derives `credit_status`, and cascades the nomination `CLOSED → DELIVERED` so the stem can be re-billed; that reopening applies when the voided invoice was the only invoice in `ISSUED` or `CREDIT_APPLIED` status on the nomination's delivered order. Voiding an invoice in `CREDIT_APPLIED` behaves identically to voiding an issued one, removing the net receivable — the amount after the remediation credit — from the customer's `outstanding_balance_usd`, re-deriving `credit_status`, and cascading the same `CLOSED → DELIVERED` reopening. An attempt to issue or void from a status that permits neither is rejected with `ERR_INVALID_INVOICE_STATE` (HTTP 409). Invoices may be listed and filtered by `delivery_order_id`, by `customer_id` or by `status`.

## 4. Endpoint Definitions

Operations that bring a new resource into existence — registering reference data, taking in a nomination, scheduling a delivery order, issuing a delivery note, filing a laboratory analysis, raising a claim or an invoice, reporting a spill — return `201 Created`. Every other operation, including all state transitions on existing resources, all administrative actions and all reads, returns `200 OK`. All paths are mounted at the root of the API.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical UTC clock | OpsCoordinator |
| POST | `/ports` | Register a bunkering port with its ECA profile, notice period and concurrent-operations capacity | OpsCoordinator |
| GET | `/ports/{id}` | Read one port | OpsCoordinator, ComplianceOfficer, CreditController, Surveyor |
| GET | `/ports` | List ports | OpsCoordinator, ComplianceOfficer, CreditController, Surveyor |
| POST | `/fuel-grades` | Register a fuel grade with its sulfur ceiling, test tolerance, barging rate and cross-contamination family | OpsCoordinator |
| GET | `/fuel-grades/{id}` | Read one fuel grade | OpsCoordinator, ComplianceOfficer, CreditController, Surveyor |
| GET | `/fuel-grades/{id}/index-quotes` | List the index quotes posted for one grade, most recent quote date first | OpsCoordinator, CreditController |
| POST | `/index-quotes` | Post an immutable index quote for a grade | OpsCoordinator, CreditController |
| POST | `/customers` | Onboard a bunker buyer with credit limit, payment terms and contractual settlement basis | CreditController |
| GET | `/customers/{id}` | Read one customer including its computed exposure fields | CreditController, OpsCoordinator |
| GET | `/customers` | List customers, optionally filtered by credit status | CreditController, OpsCoordinator |
| GET | `/customers/{id}/credit-exposure` | Computed read returning both exposure variants on the customer projection | CreditController, CustomerRep |
| POST | `/customers/{id}/credit-review` | Periodic credit review: adjust the credit limit and/or settlement basis and re-derive credit standing | CreditController |
| POST | `/delivery-assets` | Register a bunker barge or road tanker at its home port | OpsCoordinator |
| GET | `/delivery-assets/{id}` | Read one delivery asset | OpsCoordinator, ComplianceOfficer, BargeMaster |
| GET | `/delivery-assets` | List delivery assets, optionally filtered by home port, last-carried grade, status or type | OpsCoordinator, ComplianceOfficer, BargeMaster |
| POST | `/delivery-assets/{id}/return-to-service` | Lift a quarantine after every spill incident on the asset is closed | ComplianceOfficer |
| POST | `/nominations` | Intake a vessel bunker nomination: grade, quantity, delivery window, mode and ECA documentation | OpsCoordinator, CustomerRep |
| GET | `/nominations/{id}` | Read one nomination with both status dimensions and its version | OpsCoordinator, ComplianceOfficer, CustomerRep |
| GET | `/nominations` | List nominations, optionally filtered by customer, port, grade or either status dimension | OpsCoordinator, ComplianceOfficer, CustomerRep |
| POST | `/nominations/{id}/compliance-review` | ECA and specification compliance decision on the nomination: approve, reject, or reopen a rejected stem | ComplianceOfficer |
| POST | `/nominations/{id}/confirm` | Confirm the stem after compliance approval and the conservative credit check | OpsCoordinator |
| POST | `/nominations/{id}/auto-schedule` | Server-side asset selection: pick the asset, derive the slot end and create the delivery order | OpsCoordinator |
| POST | `/delivery-orders` | Schedule a barge or truck delivery against a confirmed nomination on an explicitly chosen asset and slot | OpsCoordinator |
| GET | `/delivery-orders/{id}` | Read one delivery order with both status dimensions and all measurement figures | OpsCoordinator, Surveyor, BargeMaster, CustomerRep |
| GET | `/delivery-orders` | List delivery orders, optionally filtered by nomination, asset or either status dimension | OpsCoordinator, Surveyor, BargeMaster, CustomerRep |
| POST | `/delivery-orders/{id}/clear` | Record port-authority and terminal clearance for the slot | OpsCoordinator |
| POST | `/delivery-orders/{id}/start-pumping` | Start the transfer; boom deployment and grade segregation are enforced here | BargeMaster |
| POST | `/delivery-orders/{id}/complete-pumping` | Close the transfer and record tank soundings and the meter totaliser | BargeMaster |
| POST | `/delivery-orders/{id}/joint-survey` | Record the independent surveyor's figure, as the mandatory joint survey or as a resurvey | Surveyor |
| POST | `/delivery-orders/{id}/quantity-decision` | Close the measurement dispute procedure: agree a resurveyed figure, or dispute an agreed one | Surveyor, CustomerRep |
| POST | `/delivery-orders/{id}/cancel` | Cancel a scheduled, cleared or suspended delivery order and release the asset commitment | OpsCoordinator |
| POST | `/bunker-delivery-notes` | Issue the MARPOL bunker delivery note and register the mandatory retained sample seal | OpsCoordinator |
| GET | `/bunker-delivery-notes/{id}` | Read one bunker delivery note with its derived sample custody status | OpsCoordinator, Surveyor, CustomerRep, LabTechnician |
| GET | `/bunker-delivery-notes` | List bunker delivery notes, optionally filtered by delivery order or status | OpsCoordinator, Surveyor, CustomerRep, LabTechnician |
| POST | `/bunker-delivery-notes/{id}/release-sample` | Release the retained sample to the laboratory before its retention period expires | OpsCoordinator |
| POST | `/quality-claims` | Raise a quality claim on an off-spec stem against the note's retained sample | CustomerRep |
| GET | `/quality-claims/{id}` | Read one quality claim | Surveyor, CreditController, CustomerRep, LabTechnician |
| GET | `/quality-claims` | List quality claims, optionally filtered by note, customer or status | Surveyor, CreditController, CustomerRep, LabTechnician |
| POST | `/quality-claims/{id}/decision` | Surveyor decision on the analysed claim: propose a remediation or reject an on-spec finding | Surveyor |
| POST | `/quality-claims/{id}/request-retest` | Customer rejects the proposed remediation and sends the sample for a second round | CustomerRep |
| POST | `/quality-claims/{id}/accept-remediation` | Credit control books the proposed remediation credit against the issued invoice | CreditController |
| POST | `/lab-analyses` | File a laboratory analysis of the released sample | LabTechnician |
| GET | `/lab-analyses/{id}` | Read one laboratory analysis | LabTechnician, Surveyor, CustomerRep |
| GET | `/lab-analyses` | List laboratory analyses, optionally filtered by claim, retested analysis or verdict | LabTechnician, Surveyor, CustomerRep |
| POST | `/invoices` | Raise the provisional invoice for a delivered, quantity-agreed order | CreditController |
| GET | `/invoices/{id}` | Read one invoice with all pricing components | CreditController, OpsCoordinator, CustomerRep |
| GET | `/invoices` | List invoices, optionally filtered by delivery order, customer or status | CreditController, OpsCoordinator, CustomerRep |
| POST | `/invoices/{id}/issue` | Issue the invoice to the customer under its credit terms | CreditController |
| POST | `/invoices/{id}/void` | Compensating action that voids an invoice and reverses the receivable | CreditController |
| POST | `/spill-incidents` | Report a fuel spill during a delivery | BargeMaster |
| GET | `/spill-incidents/{id}` | Read one spill incident | ComplianceOfficer, OpsCoordinator, BargeMaster |
| GET | `/spill-incidents` | List spill incidents, optionally filtered by delivery order, asset, port or status | ComplianceOfficer, OpsCoordinator, BargeMaster |
| POST | `/spill-incidents/{id}/confirm-containment` | Record the port response team's containment confirmation and case reference | ComplianceOfficer |
| POST | `/spill-incidents/{id}/close` | Close the incident once containment is confirmed, unblocking return-to-service | ComplianceOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_ROLE_NOT_PERMITTED` | 403 |
| `ERR_CUSTOMER_SCOPE_VIOLATION` | 403 |
| `ERR_ASSET_NOT_ASSIGNED` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_PORT_NOT_FOUND` | 404 |
| `ERR_FUEL_GRADE_NOT_FOUND` | 404 |
| `ERR_CUSTOMER_NOT_FOUND` | 404 |
| `ERR_ASSET_NOT_FOUND` | 404 |
| `ERR_NOMINATION_NOT_FOUND` | 404 |
| `ERR_DELIVERY_ORDER_NOT_FOUND` | 404 |
| `ERR_BDN_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_LAB_ANALYSIS_NOT_FOUND` | 404 |
| `ERR_INVOICE_NOT_FOUND` | 404 |
| `ERR_SPILL_INCIDENT_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_STALE_NOMINATION_VERSION` | 412 |
| `ERR_STALE_CLAIM_VERSION` | 412 |
| `ERR_INVALID_NOMINATION_STATE` | 409 |
| `ERR_COMPLIANCE_NOT_APPROVED` | 409 |
| `ERR_INVALID_ORDER_STATE` | 409 |
| `ERR_INVALID_MEASUREMENT_STATE` | 409 |
| `ERR_MEASUREMENT_NOT_AGREED` | 409 |
| `ERR_BDN_ALREADY_ISSUED` | 409 |
| `ERR_BDN_NOT_ISSUED` | 409 |
| `ERR_INVOICE_ALREADY_EXISTS` | 409 |
| `ERR_INVALID_INVOICE_STATE` | 409 |
| `ERR_INVOICE_NOT_ISSUED` | 409 |
| `ERR_INVALID_CLAIM_STATE` | 409 |
| `ERR_SAMPLE_NOT_RELEASED` | 409 |
| `ERR_RETEST_LIMIT_REACHED` | 409 |
| `ERR_NO_OFFSPEC_FINDING` | 409 |
| `ERR_NO_MEASUREMENT_DISCREPANCY` | 409 |
| `ERR_ASSET_QUARANTINED` | 409 |
| `ERR_INVALID_ASSET_STATE` | 409 |
| `ERR_OPEN_SPILL_INCIDENT` | 409 |
| `ERR_INVALID_SPILL_STATE` | 409 |
| `ERR_ECA_SULFUR_VIOLATION` | 422 |
| `ERR_ECA_DOCUMENTATION_MISSING` | 422 |
| `ERR_BOOM_NOT_CERTIFIED` | 422 |
| `ERR_GRADE_INCOMPATIBLE_ASSET` | 422 |
| `ERR_CONTAINMENT_NOT_CONFIRMED` | 422 |
| `ERR_ASSET_NOT_SUITABLE` | 422 |
| `ERR_WINDOW_TOO_SHORT` | 422 |
| `ERR_SLOT_OUTSIDE_WINDOW` | 422 |
| `ERR_ASSET_SLOT_CONFLICT` | 409 |
| `ERR_PORT_CAPACITY_EXCEEDED` | 409 |
| `ERR_NOTICE_PERIOD_MISSED` | 422 |
| `ERR_CLAIM_WINDOW_CLOSED` | 422 |
| `ERR_SAMPLE_RETENTION_EXPIRED` | 422 |
| `ERR_ASSET_CAPACITY_EXCEEDED` | 422 |
| `ERR_AFFECTED_QUANTITY_EXCEEDS_BASIS` | 422 |
| `ERR_MEASUREMENT_FIGURES_INCONSISTENT` | 422 |
| `ERR_DUPLICATE_REFERENCE_CODE` | 409 |
| `ERR_DUPLICATE_BDN_NUMBER` | 409 |
| `ERR_DUPLICATE_SAMPLE_SEAL` | 409 |
| `ERR_NO_ELIGIBLE_ASSET` | 409 |
| `ERR_INDEX_QUOTE_UNAVAILABLE` | 422 |
| `ERR_CUSTOMER_CREDIT_HOLD` | 402 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 |
