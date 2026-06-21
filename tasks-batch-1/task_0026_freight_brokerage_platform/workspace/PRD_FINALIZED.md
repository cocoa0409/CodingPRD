# Freight Brokerage Platform API — Product Requirements Document

## 1. Introduction

Freight brokerage sits at the intersection of three commercial actors who rarely share the same view of a shipment: the shipper who needs cargo moved at a known price, the motor carrier who is staking equipment and crew against a quoted rate, and the broker who must reconcile credit exposure, regulatory qualification, and environmental compliance before either side can be committed. Today this reconciliation happens in spreadsheets and email threads; the result is duplicate awards on the same lane, factoring advances paid on invoices that later get written off, and SmartWay compliance numbers that nobody can audit. This API replaces that ad-hoc workflow with a single transactional surface across the entire lifecycle: shipper onboarding, carrier qualification against FMCSA MC# and USDOT identifiers, spot and contract rate pricing, the load handoff from award through proof-of-delivery, accessorial billing, factoring financing, dispute claims, and quarterly SmartWay audits.

Two cross-cutting concerns shape the design. First, several business decisions — most notably awarding a quote and activating a contract rate — touch resources that competing operators are simultaneously editing, so the API exposes optimistic-concurrency guards that let well-behaved clients detect stale reads before they overwrite a peer's work. Second, freight financials are conserved quantities: the broker's open accounts-receivable, a load's accessorial total, and a factor's advance must reconcile exactly under both forward operations (issuing an invoice, recording a payment) and their compensating actions (withdrawing a dispute, denying a claim). The endpoint and validation rules below are written to enforce both invariants — concurrency safety and financial conservation — without requiring the client to reason about either.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts that govern every endpoint. Subsequent sections (workflows, the endpoint table, and the error catalogue) inherit these rules; they are not restated per endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers. `X-User-ID` identifies the acting principal and `X-User-Role` declares the operational capacity in which the principal is acting. If either header is missing or empty, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the header pair is present but the declared role is not permitted to invoke the targeted endpoint, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The platform recognizes exactly three roles, spelled as follows: `BrokerOps`, `Shipper`, and `Carrier`.

`BrokerOps` is an opaque operator identifier — the broker's internal staff who qualifies carriers, manages contracts, awards quotes, processes payments, and resolves disputes. When `X-User-Role` is `BrokerOps`, the `X-User-ID` value is not tied to any persisted entity in the system; the server treats it as a free-form operator handle that it may record for audit purposes but does not compare against any row's `id`.

`Shipper` and `Carrier` are entity-backed roles. When `X-User-Role` is `Shipper`, `X-User-ID` is the `id` of the acting `Shipper` row; ownership checks on shipper-facing resources compare the resource's `shipper_id` foreign key (resolved through `Load.quote_request_id` for downstream resources) to `X-User-ID`, and a shipper may only act on resources whose ownership chain terminates at its own `id`. When `X-User-Role` is `Carrier`, `X-User-ID` is the `id` of the acting `Carrier` row; carrier-facing list and detail endpoints filter by `carrier_id == X-User-ID`, and the pickup/deliver/factoring endpoints require the targeted `Load` or `Invoice` to belong to that same carrier.

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

List endpoints accept two query parameters for pagination. The `limit` parameter caps the number of items returned and defaults to 10 when omitted; values below 1 or above 100 are rejected. The `offset` parameter skips the leading N items in the result set and defaults to 0. Unless a more specific ordering is documented inline, every list endpoint returns rows sorted by `created_at` in ascending order, with ties broken by `id` to keep pagination deterministic across pages. Every list response surfaces `limit`, `offset`, `total_count`, and `has_more` inside the `meta` envelope so clients can drive successor-page requests without reading the body.

### 2.4. Common Resource Properties

Every primary resource — `Shipper`, `Carrier`, `ContractRate`, `QuoteRequest`, `Load`, `Invoice`, `FactoringRequest`, and `DisputeClaim` — carries four system-managed fields:

- **`id`** — a server-minted UUID assigned at creation. The identifier carries no type prefix; clients distinguish resource types by the endpoint they were retrieved from, not by parsing the `id`.
- **`created_at`** — an ISO 8601 UTC timestamp with three fractional digits, frozen at creation and never re-written.
- **`updated_at`** — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation, including the side-effect mutations described in §2.5 (a cascade that changes a parent's status also refreshes that parent's `updated_at`).
- **`version`** — a non-negative integer that starts at 1 (or any value the implementation chooses) on creation and increments by exactly one on every mutation, including state transitions and computed-field refreshes. This is the value clients pin against for optimistic concurrency (§2.6).

Two resource types are deliberate exceptions. The `Accessorial` line item is immutable once attached to a load — it has only `id` and `created_at`; neither `updated_at` nor `version` is present. The `SmartWayAudit` is likewise treated as an immutable quarterly snapshot — only `id` and `created_at` are present, and re-running the audit for the same `(shipper_id, quarter_label)` is forbidden rather than producing a new version.

### 2.5. Cascading Side Effects and Hierarchical Consistency

Many transitions in this system are not single-resource events; they propagate downward and, in some cases, sideways to maintain financial and lifecycle invariants. Whenever a transition has a documented secondary effect, the secondary resource is mutated in the same logical transaction as the primary one — its status is updated, its `updated_at` is refreshed, and its `version` is incremented by exactly one. The narrative in §3 describes each cascade; this subsection establishes the universal expectation that no cascade is "best-effort" and no cascade leaves a child stranded in a state inconsistent with its parent.

Three families of cascades recur throughout the workflows below. **Quote-to-load cascades**: awarding a `QuoteRequest` creates the `Load` row in the same transaction, copies the quoted price into `Load.agreed_rate_cents`, and advances `QuoteRequest.version`; cancelling a `Load` while it is still `AWARDED` reverses the parent quote back to `WITHDRAWN`, restoring the lane to a state where a fresh quote may be issued. **Load-to-invoice cascades**: invoicing a delivered load creates the `Invoice` row, freezing `Invoice.total_cents` at issue time via the calculation in §3.6, and full payment of that invoice cascades the parent load to `CLOSED`. **Dispute cascades**: opening a dispute claim against an invoice flips the invoice to `DISPUTED` in the same transaction; resolving the dispute then rewinds, reduces, or writes off the invoice depending on `resolution_kind`, and an `UPHELD` write-off that touches a factored invoice further cascades the related `FactoringRequest` to `RECOURSE` so the factor's advance can be recalled.

### 2.6. Optimistic Concurrency Control and Version Pinning

Two operations in this system run against parent resources that competing operators may have already mutated, and both are guarded by an explicit version-pinning input.

The first is **awarding a quote**. The award request must carry `expected_quote_request_version`, set by the client to the `version` value it last observed on the target `QuoteRequest`. If, at the moment the server processes the award, the `QuoteRequest`'s current `version` differs from `expected_quote_request_version` — for example because a sibling broker has already withdrawn the quote, or because the server has auto-expired it, or because a fresh quote on the same lane has legitimately superseded the client's view — the award is rejected with `ERR_STALE_VERSION` (HTTP 412) and no `Load` is created. The version check is non-optional: omitting `expected_quote_request_version` produces `ERR_INVALID_REQUEST` (HTTP 400), not a silent best-effort award.

The second is **activating a contract rate**. The activate request must carry `expected_contract_rate_version`, again equal to the `version` the client last observed on the target `ContractRate`. If another administrator has amended the contract's fuel surcharge or rate-per-mile in the interim, the contract's `version` will have advanced; the second activate call carrying the now-stale value is rejected with `ERR_STALE_VERSION` (HTTP 412) and the contract remains in `DRAFT`.

No other endpoint in this API accepts an `expected_<parent>_version` field, and no other endpoint produces `ERR_STALE_VERSION`. Endpoints not listed in this section do not check the parent's version on entry.

In addition to the OCC field, the award endpoint enforces a **version-pinning check** on the contract rate when the quote was priced under a contract. The `QuoteRequest` captures `contract_rate_id` and `contract_rate_version` at create time (see §3.3). At award time, if `rate_mode` is `CONTRACT`, the server compares the pinned `contract_rate_version` against the referenced `ContractRate`'s current `version` and rejects the award with `ERR_CONTRACT_RATE_STALE` (HTTP 422) on any drift — the contract's price has moved out from under the shipper's quoted total, and a fresh quote must be issued.

### 2.7. Validation Ordering and Nested-Resource Resolution

Every request runs through a strict validation pipeline before any business logic executes, and the order is observable: a request that violates several rules surfaces the rule with the lowest priority number, not the most domain-specific one. The pipeline is, in order: authentication header presence (`ERR_UNAUTHENTICATED`); role authorization for the targeted endpoint (`ERR_UNAUTHORIZED`); existence of every path-parameter resource resolved strictly left-to-right (`ERR_RESOURCE_NOT_FOUND`); existence of every foreign-key reference present in the request body (`ERR_FK_NOT_FOUND`); state-machine admissibility of the requested transition (`ERR_INVALID_STATE`); optimistic-concurrency parent-version match for the two OCC-guarded endpoints (`ERR_STALE_VERSION`); and finally the domain-specific business rules detailed throughout §3 and listed in §5.

The left-to-right path resolution matters wherever a URL nests resources. A request to list a shipper's quarterly audits under `/shippers/{id}/smartway-audits` first verifies the shipper exists — if not, `ERR_RESOURCE_NOT_FOUND` is returned for the shipper specifically, before any audit row is consulted. The same principle applies to load-scoped accessorial reads: the load is resolved first, and only after it is found does the server enumerate the attached `Accessorial` rows.

### 2.8. Monetary Precision and Rounding

Every monetary value in the system is stored and exchanged as a non-negative integer count of cents — there are no decimal currency fields, no implicit unit conversion, and no string-formatted money values. Where a calculation produces a fractional cent (for example, a SPOT-mode equipment uplift expressed as a percentage of linehaul, or a factoring advance computed against a fee percentage), the result is rounded to the nearest whole cent using the **half-up** rule before being summed into any aggregate, and the rounding happens once at the leaf rather than after intermediate accumulators. Linehaul and fuel terms whose inputs are already in whole-cent rates and whole-mile distances do not require rounding because their products are exact.

Two non-monetary rounding rules also belong here. The SmartWay compliance ratio is rounded **half-up to four decimal places** before being compared against the threshold bands. Detention minutes — fractional minutes derived from a wall-clock subtraction — are first reduced by the free window in whole minutes and only then converted to whole billable hours by **ceiling** the remainder to the next whole hour, in that order; computing whole hours before subtracting the free window would silently lose the boundary precision at the edge of the free window.

### 2.9. Financial Conservation Invariants

Two ledger-style sums are maintained as conserved quantities and are re-checked under both forward operations and their compensating actions.

The first is **shipper open accounts-receivable**. `Shipper.open_ar_cents` is, at every observable moment, the sum of `Invoice.total_cents - Invoice.amount_paid_cents` taken over every `Invoice` that reaches the shipper through its load chain (an invoice belongs to a shipper when its `load_id` resolves to a `Load` whose `quote_request_id` resolves to a `QuoteRequest` whose `shipper_id` equals the shipper) and whose `status` is one of `ISSUED`, `PARTIALLY_PAID`, or `DISPUTED`. The forward action is recording a payment: `POST /freight/invoices/{id}/payments` adds `amount_cents` to `Invoice.amount_paid_cents`, which mechanically reduces the open-AR sum. The compensating action is `POST /freight/dispute-claims/{id}/withdraw`: a dispute withdraw restores the invoice's `status` to its pre-`DISPUTED` value without changing `total_cents` or `amount_paid_cents`, so the invoice's contribution to open AR returns to the same number it held before the dispute was opened. Forward action paired with compensating action must leave `Shipper.open_ar_cents` exactly unchanged — there is no drift tolerance.

The second is the **load accessorial total**. `Load.accessorial_total_cents` is, at every observable moment, the sum of `amount_cents` taken over every `Accessorial` whose `load_id` equals the load. The forward action is `POST /freight/loads/{id}/accessorials`, which adds `amount_cents` to the running sum and refreshes the load. The compensating action is an `OVERCHARGE` dispute claim resolved as `PARTIAL` with `resolution_amount_cents` equal to the disputed accessorial's `amount_cents`: that resolution reduces `Invoice.total_cents` by exactly the same amount but does not mutate `Load.accessorial_total_cents`, preserving the broader invariant that the invoice's total equals the load's agreed rate plus its detention charge plus its accessorial total minus the cumulative partial-resolution credits.

### 2.10. Carrier Qualification and SmartWay Eligibility as Cross-Cutting Constraints

Carrier qualification is not a one-time onboarding event; it gates several downstream operations. A `Carrier` may be created in any state, but its `qualification_status` begins at `PENDING` and the carrier is ineligible to be awarded a load, to request factoring, or to be reinstated until it reaches `QUALIFIED`. Qualification itself requires the carrier's `mc_number` and `usdot_number` to remain valid format-wise, `insurance_expiry_utc` to be strictly later than the server's current UTC moment, and `safety_score` to be strictly less than 75.0 — the latter being the FMCSA SMS rejection threshold the platform tracks. Carrier insurance is re-verified at award time too: a `QuoteRequest` cannot be awarded to a `QUALIFIED` carrier whose insurance has lapsed since qualification, and reinstating a `SUSPENDED` carrier likewise requires the insurance to be in date.

SmartWay eligibility is a separate, opt-in dimension. A `QuoteRequest` carries a `requires_smartway` flag; when the flag is true, the award endpoint additionally checks that the chosen carrier's `smartway_tier` is one of `BRONZE`, `SILVER`, or `GOLD`, rejecting `NONE`-tier carriers with `ERR_SMARTWAY_INELIGIBLE`. The platform tracks shipper-level SmartWay performance retroactively via quarterly audits; see §3.8.

## 3. Business Logic & Workflows

The subsections below trace the freight lifecycle from the shipper-and-carrier onboarding edges inward to the load handoff, then forward through billing, factoring, disputes, and compliance auditing. Several subsections deliberately weave cross-cutting concerns — safety, version-pinning, conservation — into the workflow where they apply rather than collecting them in a single place; readers reconstructing implementation behavior from this section should expect, for example, the credit-limit guard to live with quote creation and the factoring-fee floor to live with factoring rather than both being co-located in a "constraints" subsection.

### 3.1. Onboarding Shippers and Carriers

A shipper is registered by a `BrokerOps` operator with three input attributes: the registered company name `legal_name`, a primary accounts-payable contact at `billing_email`, and an integer `credit_limit_cents` that is the broker's exposure ceiling for the shipper's open invoices. The credit limit must be at least zero. The new row's `status` is `ACTIVE` and the system-managed `open_ar_cents` accumulator begins at zero. A shipper that has accumulated too much delinquency may be moved to `ON_HOLD` by the platform; while `ON_HOLD`, the shipper's contracts may not be activated. The two `Shipper` lifecycle states are exactly `ACTIVE` and `ON_HOLD`.

Carrier onboarding is more rigorous. A `BrokerOps` operator registers a carrier with `legal_name`, the FMCSA Motor Carrier number `mc_number`, the USDOT registration `usdot_number`, the carrier's EPA `smartway_tier`, the `insurance_expiry_utc` from the certificate of liability insurance, and the FMCSA SMS `safety_score`. The `mc_number` must be a 6- or 7-digit numeric string and the `usdot_number` a 5- to 8-digit numeric string; each value must be unique across the carrier table. A registration that violates the format or uniqueness rule is rejected with `ERR_INVALID_MC_USDOT`. The `safety_score` is a real-valued FMCSA SMS score on the closed interval from zero to one hundred, where a lower number indicates a safer carrier. The `smartway_tier` enumerates four values — `NONE`, `BRONZE`, `SILVER`, `GOLD` — and defaults to `NONE` when omitted at registration. The new row starts with `qualification_status` `PENDING` and a null `rejection_reason_code`.

The qualification workflow runs four checks. To advance a carrier from `PENDING` to `QUALIFIED`, the operator confirms (in this order) that `mc_number` still matches the 6-or-7-digit pattern, that `usdot_number` still matches the 5-to-8-digit pattern, that `insurance_expiry_utc` is strictly after the current server time, and that `safety_score` is strictly below 75.0. The safety check, when it fails, surfaces as `ERR_SAFETY_SCORE_TOO_HIGH`; the insurance check, when it fails, surfaces as `ERR_INSURANCE_EXPIRED`. The qualifying operator does not supply a body. A rejecting operator, by contrast, must supply a `reason_code` taken from the enumeration `BAD_MC`, `BAD_USDOT`, `INSURANCE_EXPIRED`, or `SAFETY_OVER_THRESHOLD`; the supplied value is recorded on the carrier as `rejection_reason_code`. A rejected carrier is terminal — there is no path out of `REJECTED`.

Once `QUALIFIED`, a carrier may be moved to `SUSPENDED` by a `BrokerOps` operator at any time without supplying a reason. A suspended carrier may be brought back to `QUALIFIED` by reinstatement, which re-verifies `insurance_expiry_utc` against the current server time and rejects with `ERR_INSURANCE_EXPIRED` if the insurance has since lapsed. Carrier lifecycle states are therefore `PENDING`, `QUALIFIED`, `REJECTED`, and `SUSPENDED`, with the transitions `PENDING → QUALIFIED`, `PENDING → REJECTED`, `QUALIFIED → SUSPENDED`, and `SUSPENDED → QUALIFIED` as the only legal moves.

### 3.2. Negotiating Contract Rates

A `ContractRate` codifies a pre-negotiated price between a single shipper and the broker for a single origin-destination lane over a finite time window. Each row is associated with the shipper that signed it (`shipper_id`), the lane's origin and destination expressed as 5-digit U.S. ZIP codes (`lane_origin` and `lane_destination`, each matching exactly five decimal digits), the all-in linehaul rate per mile in cents (`rate_per_mile_cents`, strictly positive), the fuel adjustment per mile in cents added on top of linehaul (`fuel_surcharge_per_mile_cents`, at least zero), the free detention window per stop in whole minutes before detention billing begins (`detention_free_minutes`, at least zero), the per-hour detention charge after the free window (`detention_rate_per_hour_cents`, at least zero), and the inclusive-start / exclusive-end UTC window over which the contract is in force (`effective_from_utc` and `effective_until_utc`). On creation the window must satisfy `effective_from_utc` strictly less than `effective_until_utc`; otherwise the request is rejected with `ERR_CONTRACT_WINDOW_INVALID`. A new row enters `DRAFT`.

Activation is a guarded transition. A `BrokerOps` operator activating a `DRAFT` contract supplies `expected_contract_rate_version` carrying the contract's last observed `version`. The server requires the contract's effective window to bracket the current server time — specifically, `effective_from_utc` no later than the current UTC and `effective_until_utc` strictly later — and the owning shipper's `status` to be `ACTIVE`. The activate call also enforces a non-overlap rule on the broker's active book: no other `ContractRate` may already be `ACTIVE` for the same `(shipper_id, lane_origin, lane_destination)` tuple with a time window that overlaps this row's window, where each window is treated as the half-open interval starting at `effective_from_utc` and ending at `effective_until_utc`; adjacency (one contract's `effective_until_utc` exactly equal to another's `effective_from_utc`) is not an overlap. An overlap is rejected with `ERR_CONTRACT_WINDOW_OVERLAP`. A stale `expected_contract_rate_version` is rejected with `ERR_STALE_VERSION` (HTTP 412). On success the contract moves `DRAFT → ACTIVE` and the `version` advances by one.

An `ACTIVE` contract may be terminated by `BrokerOps` at any time; it transitions to `TERMINATED` and is terminal in that state. A separate system-driven transition advances any `ACTIVE` contract to `EXPIRED` once the server's current time reaches or passes `effective_until_utc`. The auto-expiration is realized by a test-driving endpoint (§3.9) rather than by polling. Contract lifecycle states are therefore `DRAFT`, `ACTIVE`, `EXPIRED`, and `TERMINATED`.

### 3.3. Pricing and Issuing a Quote

A shipper (or a `BrokerOps` operator acting on the shipper's behalf — the operation is shared between the two roles) requests a quote with `shipper_id`, the lane's `lane_origin` and `lane_destination` ZIPs, the pre-computed road distance `distance_miles` (a positive whole-mile integer), the requested pickup window `pickup_window_start_utc` (inclusive) and `pickup_window_end_utc` (exclusive), the equipment type `requested_equipment` from the enumeration `DRY_VAN`, `REEFER`, or `FLATBED`, and an optional `requires_smartway` boolean that defaults to false when omitted.

The pickup window must satisfy two conditions: `pickup_window_start_utc` must be strictly earlier than `pickup_window_end_utc`, and `pickup_window_start_utc` must be strictly later than the current server time. Violations are rejected with `ERR_TIME_WINDOW_INVALID`. The platform additionally guards against duplicate open quotes on the same lane: a new `QuoteRequest` is rejected with `ERR_QUOTE_WINDOW_OVERLAP` if there already exists an `OPEN` quote for the same `(shipper_id, lane_origin, lane_destination)` whose pickup window — expanded on the left by a 120-minute pre-pickup buffer to form the effective interval starting at `pickup_window_start_utc` minus 120 minutes and ending at `pickup_window_end_utc` — overlaps the incoming request's similarly-buffered window. The left boundary is closed after the buffer expansion, meaning adjacency at the buffered edge counts as an overlap.

The quote also runs a credit guard at creation time. The server first computes an estimated quote total using a conservative SPOT-mode pricing path (SPOT distance tier with no equipment uplift) and then verifies that `Shipper.open_ar_cents` plus that estimate does not exceed `Shipper.credit_limit_cents`. A breach is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`. The guard runs only at quote creation; it is not re-evaluated at award time.

If all validation passes, the server resolves `rate_mode`. It searches `ContractRate` rows for a row that satisfies, jointly, that the contract's `shipper_id` matches the request's shipper, that `lane_origin` and `lane_destination` are equal under strict 5-digit-ZIP comparison, that `effective_from_utc` is no later than the request's `pickup_window_start_utc` and `effective_until_utc` is strictly later than it, and that the contract's `status` is `ACTIVE`. Of the rows satisfying all four conditions, the row with the earliest `created_at` is chosen (ties broken in `created_at` ascending order, with the first row picked). When such a row exists, `rate_mode` is set to `CONTRACT`, `contract_rate_id` is set to the chosen row's `id`, and `contract_rate_version` is captured from the chosen row's current `version`. The quoted total is then the sum of the linehaul term (the contract's `rate_per_mile_cents` multiplied by `distance_miles`) and the fuel term (the contract's `fuel_surcharge_per_mile_cents` multiplied by `distance_miles`); contract pricing uses no tier table and applies no equipment uplift, and both terms are exact whole-cent products of whole-cent rates and whole-mile distances.

When no covering contract row exists, `rate_mode` is `SPOT`, `contract_rate_id` is null, and `contract_rate_version` is null. SPOT pricing applies a distance-tiered per-mile rate: for `distance_miles` of at most 250, the per-mile rate is 320 cents; for `distance_miles` of 251 through 750 inclusive, the per-mile rate is 235 cents; for `distance_miles` of 751 or more, the per-mile rate is 195 cents. The linehaul term is the chosen per-mile rate multiplied by `distance_miles`, and the fuel term is a flat 65 cents per mile multiplied by `distance_miles`. SPOT pricing further adds an equipment uplift expressed as a percentage of linehaul: `DRY_VAN` adds 0 percent, `REEFER` adds 18 percent, and `FLATBED` adds 10 percent. The uplift is rounded to the nearest whole cent half-up before being summed into `quoted_total_cents`; the resulting total is linehaul plus fuel plus the rounded uplift.

The server stores `quoted_total_cents` on the new row. It also sets `expires_at_utc` equal to `pickup_window_start_utc`, fixing the latest moment at which the quote can still be awarded before it auto-expires. The new row's `status` is `OPEN`. Quote lifecycle states are exactly `OPEN`, `AWARDED`, `EXPIRED`, and `WITHDRAWN`.

A shipper may withdraw an `OPEN` quote at any time; the quote moves to `WITHDRAWN` and is terminal there. The platform separately advances any `OPEN` quote to `EXPIRED` once the current server time reaches or passes `expires_at_utc`; this transition is performed by the test-driving clock-advance endpoint (§3.9) when invoked.

### 3.4. Awarding a Quote and Creating the Load

Awarding is the most heavily guarded transition in the system because it is the moment a price quoted to the shipper becomes a commitment between the broker and a specific carrier. A `BrokerOps` operator awards an `OPEN` quote by supplying `carrier_id` and `expected_quote_request_version`. The award runs five preconditions in addition to the standard pipeline: the quote's `status` must be `OPEN`; the current server time must be strictly earlier than the quote's `expires_at_utc`; the chosen carrier's `qualification_status` must be `QUALIFIED`; if the quote has `requires_smartway` set to true, the carrier's `smartway_tier` must be one of `BRONZE`, `SILVER`, or `GOLD`; and if `rate_mode` is `CONTRACT`, the referenced `ContractRate` must still be `ACTIVE` and its current `version` must match the quote's pinned `contract_rate_version`. The SmartWay failure surfaces as `ERR_SMARTWAY_INELIGIBLE`; the carrier-insurance lapse surfaces as `ERR_INSURANCE_EXPIRED` (the carrier's `insurance_expiry_utc` is also re-verified strictly after the current server time at award); the contract-version drift surfaces as `ERR_CONTRACT_RATE_STALE`.

Independently of the business-rule checks, the OCC guard runs: if `expected_quote_request_version` does not equal the quote's current `version`, the award is rejected with `ERR_STALE_VERSION` (HTTP 412). The OCC guard is framed entirely in stale-version terms, not in race-window terms: the canonical case is that the client read `version` N moments earlier and another broker has since legitimately withdrawn-and-reissued the quote (advancing `version` past N), so the client's award attempt is against a view the server can no longer honor.

When all checks pass, the server performs the award as a single transaction: the quote moves `OPEN → AWARDED` and its `version` advances by one; a new `Load` row is created with `quote_request_id` set to the quote's `id`, `carrier_id` set to the supplied carrier, `agreed_rate_cents` set to the quote's `quoted_total_cents`, `detention_charge_cents` initialized to zero, `accessorial_total_cents` initialized to zero, `pod_received_at_utc` initialized to null, `actual_pickup_at_utc` and `actual_delivery_at_utc` initialized to null, and `status` set to `AWARDED`. The award endpoint returns the newly created `Load`, not the quote, because the load is the entity the operator will reference for every subsequent step.

### 3.5. Executing the Load: Pickup, Delivery, and Accessorials

Once a `Load` is `AWARDED`, the awarded carrier owns its execution and reports two milestones. Pickup is reported by the carrier supplying `actual_pickup_at_utc`, the wall-clock UTC moment the truck arrived at the shipper's dock. The load transitions `AWARDED → IN_TRANSIT`, `Load.actual_pickup_at_utc` records the supplied value, and the load's `version` advances by one. Pickup before-or-after the original pickup window is permitted; the divergence is what powers the detention calculation at delivery.

Delivery is reported by the carrier supplying `actual_delivery_at_utc`, which must be strictly later than the previously recorded `actual_pickup_at_utc`; otherwise the request is rejected with `ERR_DELIVERY_BEFORE_PICKUP`. The load transitions `IN_TRANSIT → DELIVERED`. In the same transaction, `Load.actual_delivery_at_utc` records the supplied value, `Load.pod_received_at_utc` is stamped with the current server time (this is the platform's marker that proof-of-delivery has been filed), and the pickup-detention calculation runs against the load to populate `Load.detention_charge_cents`. The detention calculation is described in §3.6.

While a load is `DELIVERED`, the carrier or a `BrokerOps` operator may attach an `Accessorial` charge to it. Each accessorial line item carries the parent `load_id`, a `code` drawn from the enumeration `LUMPER`, `TARPS`, `EXTRA_STOP`, `REWEIGH`, `LAYOVER`, or `DETENTION`, a strictly positive `amount_cents`, and an optional free-text `note`. Attaching an accessorial recomputes `Load.accessorial_total_cents` as the sum of `amount_cents` across all accessorials on the load and increments the load's `version` by one. Accessorial rows themselves are immutable line items — they carry only `id` and `created_at`, with no `updated_at` or `version`.

A `BrokerOps` operator may cancel an `AWARDED` load before pickup. Cancellation transitions the load `AWARDED → CANCELLED` and cascades the parent quote back to `WITHDRAWN`, advancing both `Load.version` and `QuoteRequest.version` by one. The cascade exists so that the lane is once again eligible for a fresh quote without leaving the original `QuoteRequest` stranded in `AWARDED`; once the load is `IN_TRANSIT` or later, this path is no longer available. Load lifecycle states are exactly `AWARDED`, `IN_TRANSIT`, `DELIVERED`, `INVOICED`, `CLOSED`, and `CANCELLED`.

### 3.6. Invoicing, Detention Math, and Invoice Lifecycle

A delivered load is invoiced by a `BrokerOps` operator, which transitions the load `DELIVERED → INVOICED` and creates the `Invoice` row in the same transaction. The transition requires `Load.pod_received_at_utc` to be present (i.e., delivery must have been reported) and the load to be in `DELIVERED` status. The new invoice's `load_id` references the load; `factored` initializes to false; `amount_paid_cents` initializes to zero; and `status` initializes to `ISSUED`. `Invoice.total_cents` is computed at issue time as the sum of the load's `agreed_rate_cents`, the load's `detention_charge_cents`, and the running sum of `Accessorial.amount_cents` over every accessorial whose `load_id` matches the load, minus the running sum of `resolution_amount_cents` over every `RESOLVED` dispute claim on this invoice whose `resolution_kind` is `PARTIAL`. The calculation sums first and subtracts second; the partial-resolution credits are not netted per-line. At issue time, before any disputes have been raised, the subtractive term is zero and the formula reduces to the additive sum. The same formula is re-run later when a `PARTIAL` dispute resolution lands — see §3.7.

The detention charge that flows into `Invoice.total_cents` is computed at delivery time and only at delivery time. The platform treats pickup detention as the billable event; any delay at delivery itself is billed as a separately-attached `Accessorial` of code `DETENTION` rather than rolled into the detention calculation. The pickup-detention math runs as follows. The raw detention minutes at pickup are the wall-clock difference between `Load.actual_pickup_at_utc` and the originating `QuoteRequest.pickup_window_start_utc`, taken in seconds and divided by sixty with the floor — yielding whole minutes — and then clipped at zero so that early pickups produce zero detention rather than a negative figure. From that raw minute count the platform subtracts a free-minute window: for `CONTRACT`-mode quotes, the window is the chosen `ContractRate.detention_free_minutes`; for `SPOT`-mode quotes, the window is 120 minutes. The result is clipped at zero, then converted to whole billable hours by **ceiling** the value divided by sixty up to the next whole hour. The whole-hour count is then multiplied by the per-hour detention rate — `ContractRate.detention_rate_per_hour_cents` in CONTRACT mode, or a flat 7500 cents per hour in SPOT mode — to yield `Load.detention_charge_cents`. The subtract-then-ceiling order matters: ceiling first would silently lose the boundary precision at the edge of the free window.

An invoice in `ISSUED` accepts payments. A payment request supplies `amount_cents` (which must be strictly positive — a zero or negative amount is rejected with `ERR_PAYMENT_OVERAGE`) and the server applies it to `Invoice.amount_paid_cents`. The post-application `amount_paid_cents` is compared against `Invoice.total_cents`: if it equals the total, the invoice transitions to `PAID`; if it is strictly less than the total, the invoice transitions to `PARTIALLY_PAID`; if it would exceed the total, the request is rejected with `ERR_PAYMENT_OVERAGE` and no state change occurs. An invoice already in `PARTIALLY_PAID` accepts further payments under the same rules; once `PAID`, no further payments are accepted. Whenever a payment lands, `Shipper.open_ar_cents` is recomputed in the same transaction so the AR conservation invariant in §2.9 continues to hold. When a payment carries the invoice to `PAID`, the cascade additionally moves the parent load `INVOICED → CLOSED`, advancing the load's `version` by one.

Invoice lifecycle states are `ISSUED`, `PARTIALLY_PAID`, `PAID`, `DISPUTED`, and `WRITTEN_OFF`. Disputed and written-off transitions are described next.

### 3.7. Dispute Claims and Resolution

A shipper that contests a charge files a `DisputeClaim` against the invoice. The claim carries `invoice_id`, a `claim_type` from the enumeration `OVERCHARGE`, `DAMAGED_GOODS`, `LATE_DELIVERY`, or `MISSING_POD`, and `claimed_amount_cents` — the strictly positive cent amount the shipper is contesting. The contested amount is capped: `claimed_amount_cents` must be no greater than `Invoice.total_cents` minus `Invoice.amount_paid_cents`, i.e., the still-open balance on the invoice. A breach is rejected with `ERR_DISPUTE_AMOUNT_EXCEEDS_OPEN`. Opening a dispute is permitted only while the invoice is `ISSUED` or `PARTIALLY_PAID`. When the claim is created, the new `DisputeClaim` row enters `OPEN`, and in the same transaction the parent invoice transitions to `DISPUTED`, advancing `Invoice.version` by one. `resolution_amount_cents` and `resolution_kind` on the claim are null at this point; they are populated only at resolution.

A `BrokerOps` operator resolves an `OPEN` claim by supplying `resolution_kind` from the enumeration `UPHELD`, `PARTIAL`, or `DENIED`, together with `resolution_amount_cents`. The resolution amount must obey, by case: when `resolution_kind` is `DENIED`, `resolution_amount_cents` must be exactly zero; when `resolution_kind` is `UPHELD`, `resolution_amount_cents` must equal the still-open balance on the invoice (`Invoice.total_cents` minus `Invoice.amount_paid_cents`); when `resolution_kind` is `PARTIAL`, `resolution_amount_cents` must be strictly greater than zero and strictly less than that same still-open balance. A violation of any of these bounds is rejected with `ERR_RESOLUTION_AMOUNT_INVALID`. In every case the resolved claim moves to `RESOLVED` and `DisputeClaim.version` advances by one.

The invoice-side effect depends on `resolution_kind`. A `DENIED` resolution rewinds the invoice: `Invoice.status` reverts to `ISSUED` if `amount_paid_cents` is zero or to `PARTIALLY_PAID` otherwise, `Invoice.total_cents` is unchanged, and `Shipper.open_ar_cents` reflects the rewind via the AR-conservation recomputation. A `PARTIAL` resolution also rewinds the invoice's status under the same `ISSUED`-or-`PARTIALLY_PAID` rule, but additionally re-runs the invoice-total calculation with the new partial-credit term — the net effect being that `Invoice.total_cents` is reduced by exactly `resolution_amount_cents`, and `Shipper.open_ar_cents` is recomputed to reflect both the status change and the total reduction. An `UPHELD` resolution writes the invoice off: `Invoice.status` moves to `WRITTEN_OFF` and `Shipper.open_ar_cents` is recomputed (because written-off invoices no longer contribute to the open-AR sum), and the cascade then continues — the parent `Load` moves to `CLOSED`, and if `Invoice.factored` is true the related `FactoringRequest` moves to `RECOURSE` so the broker can recall the advance from the factor. Each cascaded entity has its `version` advanced by one.

A shipper may also withdraw an `OPEN` dispute. Withdrawal moves the claim to `WITHDRAWN` and reverts the invoice's `status` to whichever value it held before the dispute opened. The withdrawal does not change `Invoice.total_cents` or `Invoice.amount_paid_cents`; combined with the open-AR recomputation, the withdrawal exactly undoes the open-AR delta that the dispute introduced, which is the conservation invariant in §2.9 in action. Both `Invoice.version` and `DisputeClaim.version` advance by one on withdrawal. `DisputeClaim` lifecycle states are exactly `OPEN`, `RESOLVED`, and `WITHDRAWN`.

### 3.8. Factoring Advances and SmartWay Quarterly Audits

A carrier may finance an open invoice by requesting a factoring advance. The request supplies `invoice_id` (the invoice being factored), `carrier_id` (the requesting carrier — must equal the load's awarded carrier), and `factoring_fee_pct` (the discount rate the factor will charge, expressed as a percent value such as 2.5 meaning 2.5%; strictly greater than zero and no greater than ten). The invoice must be in `ISSUED` or `PARTIALLY_PAID` status and not already factored. The requesting carrier must be `QUALIFIED`. The factoring fee is subject to a safety-tiered floor: for a carrier whose `safety_score` is strictly less than 25, the floor is 2.0 percent; for a carrier whose `safety_score` is at least 25 and strictly less than 50, the floor is 2.5 percent; for a carrier whose `safety_score` is at least 50 and strictly less than 75, the floor is 3.5 percent. (Carriers with `safety_score` at or above 75 cannot be `QUALIFIED` and so cannot reach this endpoint.) A submitted `factoring_fee_pct` below the applicable floor is rejected with `ERR_FACTORING_FEE_BELOW_MIN`.

The platform computes `advance_cents` at request time using the larger of the submitted `factoring_fee_pct` and the safety-tiered floor as the **actual fee percent**. The raw advance equals `Invoice.total_cents` multiplied by the quantity (one hundred minus the actual fee percent) divided by one hundred; that raw value is then rounded to the nearest whole cent half-up to produce `advance_cents`. The rounding happens once, at the end, on the single raw value. The new `FactoringRequest` row enters `REQUESTED` status.

A `BrokerOps` operator approves the request, moving it `REQUESTED → APPROVED` and flipping `Invoice.factored` to true in the same transaction (`Invoice.version` advances). The operator subsequently disburses funds, moving the request `APPROVED → ADVANCED`. Either of these transitions may be replaced by `REQUESTED → REJECTED` instead, which is terminal. The terminal `RECOURSE` state is reached only by cascade from an `UPHELD` dispute write-off (see §3.7) or, equivalently, by an explicit recourse call when the related invoice is in `WRITTEN_OFF` status. `FactoringRequest` lifecycle states are `REQUESTED`, `APPROVED`, `ADVANCED`, `REJECTED`, and `RECOURSE`.

The platform's SmartWay compliance posture is computed retroactively per calendar quarter per shipper. A `SmartWayAudit` is created by a `BrokerOps` operator supplying `shipper_id` and `quarter_label`, where `quarter_label` is a four-digit year followed by the literal letter `Q` and a digit one through four (for example `2026Q2`). The label must match that pattern, the quarter must already be complete (i.e., the quarter's end UTC moment must be strictly earlier than the server's current time), and the pair `(shipper_id, quarter_label)` must be unique across the audit table — duplicates are rejected with `ERR_AUDIT_QUARTER_INVALID`. The same error covers all three audit-input failures.

The audit body computes three derived fields. The `total_loads` count enumerates `Load` rows whose owning `QuoteRequest.shipper_id` equals the audit's shipper, whose `status` is one of `DELIVERED`, `INVOICED`, or `CLOSED`, and whose `actual_delivery_at_utc` falls within the half-open quarter interval (inclusive on the quarter's start UTC, exclusive on the quarter's end UTC). The `smartway_loads` count is the subset of those whose awarded `Carrier.smartway_tier` at delivery time is one of `BRONZE`, `SILVER`, or `GOLD`. The `smartway_ratio` is `smartway_loads` divided by `total_loads`, rounded half-up to four decimal places; when `total_loads` is zero, the ratio is fixed at zero. The audit's `compliance_status` is then derived from the ratio against two thresholds: a ratio at or above 0.60 is `PASSING`, a ratio at or above 0.40 but strictly below 0.60 is `AT_RISK`, and a ratio strictly below 0.40 is `FAILING`. A zero-load audit (total_loads is zero, ratio is zero) is `FAILING`. The ratio is rounded before the threshold comparison, and the boundary tie at exactly 0.60 maps to `PASSING` while the tie at exactly 0.40 maps to `AT_RISK`.

### 3.9. Shipper Credit Risk and Test-Driving the Logical Clock

Shipper credit risk is exposed as a read-only computation rather than a stored attribute. When a `BrokerOps` operator requests the credit-risk read on a shipper, the platform computes four numbers in sequence. First, the `utilization_ratio` is `Shipper.open_ar_cents` divided by the maximum of `Shipper.credit_limit_cents` and one (the `max(·, 1)` guard prevents a divide-by-zero on a zero-credit-limit shipper). Second, the `late_count` is the number of `Invoice` rows reaching this shipper through its load chain whose `status` is `PARTIALLY_PAID` and whose age — measured as the current server time minus `Invoice.created_at` — exceeds thirty days. Third, the `dispute_count` is the number of `DisputeClaim` rows reaching this shipper through the same chain whose `status` is `RESOLVED` and whose `resolution_kind` is anything other than `DENIED`. Open invoices are counted regardless of their factoring status.

The composite credit-risk `score` is then computed as 0.6 multiplied by the minimum of `utilization_ratio` and 1.0 multiplied by 100 (no intermediate rounding on the utilization term), plus 5 multiplied by `late_count`, plus 8 multiplied by `dispute_count`. The result is rounded half-up to a whole integer. The response surfaces four named fields — `score`, `utilization_ratio`, `late_count`, and `dispute_count` — drawn directly from this computation. The credit-risk read is also implicitly recomputed on every `Invoice` status change so that downstream views remain consistent.

Two system-driven transitions in this system are time-dependent: `OPEN` quotes auto-expire when `expires_at_utc` is reached, and `ACTIVE` contracts auto-expire when `effective_until_utc` is reached. To make these transitions observable under test, the platform exposes two administrative capabilities. The first pins the server's logical current time to a literal ISO 8601 UTC instant supplied as `to_iso8601`; the second triggers the system-time-driven sweep against the freshly pinned clock. At server startup, before any client has invoked `POST /freight/_clock/set_current_utc`, the logical clock is initialized to `2025-01-01T00:00:00.000Z`; every time-dependent check elsewhere in this PRD (quote expiry, contract activation window bracketing, audit quarter completion, insurance expiry at qualify/reinstate/award, pickup-window-strictly-in-future) reads from this single mutable instant. Invoking the sweep returns two arrays — the `id` of every `QuoteRequest` that just transitioned from `OPEN` to `EXPIRED`, and the `id` of every `ContractRate` that just transitioned from `ACTIVE` to `EXPIRED`. Each transition advances the corresponding entity's `version` by one. Both capabilities are restricted to `BrokerOps` because they alter time across the entire deployment.

## 4. Endpoint Definitions

The table below lists every endpoint exposed by the API. Operations that introduce a new top-level resource (a shipper, a carrier, a contract rate, a quote request, an invoice, a factoring request, a dispute claim, an accessorial line item, or a SmartWay audit) return HTTP 201. Operations that modify an existing resource — including all state-machine transitions, payment application, and the test-driving clock endpoints — return HTTP 200. Read endpoints return HTTP 200. The request and response bodies, side effects, validation order, and error mapping for each endpoint are governed by §2 and §3 and are not restated in this table.

| Method | Path                                                  | Description                                                                        | Authorized Role(s)        |
| ------ | ----------------------------------------------------- | ---------------------------------------------------------------------------------- | ------------------------- |
| POST   | `/freight/shippers`                                   | Register a new shipper.                                                            | BrokerOps                 |
| GET    | `/freight/shippers/{id}`                              | Fetch one shipper.                                                                 | BrokerOps, Shipper        |
| GET    | `/freight/shippers`                                   | List shippers; supports status filter.                                             | BrokerOps                 |
| GET    | `/freight/shippers/{id}/credit-risk`                  | Compute and return the shipper's current credit-risk score.                        | BrokerOps                 |
| POST   | `/freight/carriers`                                   | Register a carrier in PENDING qualification status.                                | BrokerOps                 |
| GET    | `/freight/carriers/{id}`                              | Fetch one carrier.                                                                 | BrokerOps, Carrier        |
| GET    | `/freight/carriers`                                   | List carriers; supports qualification_status filter.                               | BrokerOps                 |
| POST   | `/freight/carriers/{id}/qualify`                      | Approve carrier qualification (PENDING → QUALIFIED).                               | BrokerOps                 |
| POST   | `/freight/carriers/{id}/reject`                       | Reject carrier (PENDING → REJECTED) with a reason code.                            | BrokerOps                 |
| POST   | `/freight/carriers/{id}/suspend`                      | Suspend a qualified carrier (QUALIFIED → SUSPENDED).                               | BrokerOps                 |
| POST   | `/freight/carriers/{id}/reinstate`                    | Reinstate a suspended carrier (SUSPENDED → QUALIFIED).                             | BrokerOps                 |
| POST   | `/freight/contract-rates`                             | Create a contract rate in DRAFT.                                                   | BrokerOps                 |
| GET    | `/freight/contract-rates/{id}`                        | Fetch one contract rate.                                                           | BrokerOps, Shipper        |
| GET    | `/freight/contract-rates`                             | List contract rates; supports filtering by shipper_id and status.                  | BrokerOps, Shipper        |
| POST   | `/freight/contract-rates/{id}/activate`               | Activate a DRAFT contract (DRAFT → ACTIVE). OCC-guarded.                           | BrokerOps                 |
| POST   | `/freight/contract-rates/{id}/terminate`              | Terminate an ACTIVE contract (ACTIVE → TERMINATED).                                | BrokerOps                 |
| POST   | `/freight/quote-requests`                             | Request a quote on a lane and equipment; rate_mode and quoted_total_cents computed.| Shipper, BrokerOps        |
| GET    | `/freight/quote-requests/{id}`                        | Fetch one quote request.                                                           | Shipper, BrokerOps        |
| GET    | `/freight/quote-requests`                             | List quote requests; supports filtering.                                           | Shipper, BrokerOps        |
| POST   | `/freight/quote-requests/{id}/award`                  | Award a quote to a specific carrier; creates the Load. OCC-guarded.                | BrokerOps                 |
| POST   | `/freight/quote-requests/{id}/withdraw`               | Shipper withdraws an OPEN quote.                                                   | Shipper                   |
| GET    | `/freight/loads/{id}`                                 | Fetch one load.                                                                    | BrokerOps, Carrier, Shipper |
| GET    | `/freight/loads`                                      | List loads; supports filtering by quote_request_id, carrier_id, status.            | BrokerOps, Carrier, Shipper |
| POST   | `/freight/loads/{id}/pickup`                          | Carrier reports pickup (AWARDED → IN_TRANSIT).                                     | Carrier                   |
| POST   | `/freight/loads/{id}/deliver`                         | Carrier reports delivery (IN_TRANSIT → DELIVERED); detention charge computed.      | Carrier                   |
| POST   | `/freight/loads/{id}/cancel`                          | Cancel an AWARDED load; cascades QuoteRequest back to WITHDRAWN.                   | BrokerOps                 |
| POST   | `/freight/loads/{id}/invoice`                         | Generate an Invoice from a DELIVERED load (DELIVERED → INVOICED).                  | BrokerOps                 |
| POST   | `/freight/loads/{id}/accessorials`                    | Attach an Accessorial line item to a DELIVERED load.                               | BrokerOps, Carrier        |
| GET    | `/freight/loads/{id}/accessorials`                    | List accessorials on a load.                                                       | BrokerOps, Carrier, Shipper |
| GET    | `/freight/invoices/{id}`                              | Fetch one invoice.                                                                 | BrokerOps, Shipper, Carrier |
| GET    | `/freight/invoices`                                   | List invoices; supports filter by load_id and status.                              | BrokerOps, Shipper, Carrier |
| POST   | `/freight/invoices/{id}/payments`                     | Record a cash receipt against an invoice.                                          | BrokerOps                 |
| POST   | `/freight/factoring-requests`                         | Carrier requests factoring on an open invoice; advance_cents computed.             | Carrier                   |
| GET    | `/freight/factoring-requests/{id}`                    | Fetch one factoring request.                                                       | BrokerOps, Carrier        |
| GET    | `/freight/factoring-requests`                         | List factoring requests; supports filtering.                                       | BrokerOps, Carrier        |
| POST   | `/freight/factoring-requests/{id}/approve`            | Approve a factoring request (REQUESTED → APPROVED).                                | BrokerOps                 |
| POST   | `/freight/factoring-requests/{id}/advance`            | Disburse the advance (APPROVED → ADVANCED).                                        | BrokerOps                 |
| POST   | `/freight/factoring-requests/{id}/reject`             | Reject a factoring request (REQUESTED → REJECTED).                                 | BrokerOps                 |
| POST   | `/freight/dispute-claims`                             | Shipper opens a dispute claim against an invoice.                                  | Shipper                   |
| GET    | `/freight/dispute-claims/{id}`                        | Fetch one dispute claim.                                                           | BrokerOps, Shipper        |
| GET    | `/freight/dispute-claims`                             | List dispute claims; supports filtering.                                           | BrokerOps, Shipper        |
| POST   | `/freight/dispute-claims/{id}/resolve`                | Broker resolves an OPEN dispute (UPHELD / PARTIAL / DENIED).                       | BrokerOps                 |
| POST   | `/freight/dispute-claims/{id}/withdraw`               | Shipper withdraws an OPEN dispute; invoice reverts to pre-DISPUTED status.         | Shipper                   |
| POST   | `/freight/smartway-audits`                            | Create a SmartWay audit for a shipper and quarter.                                 | BrokerOps                 |
| GET    | `/freight/smartway-audits`                            | List SmartWay audits; supports filtering by shipper_id, quarter_label, compliance_status. | BrokerOps, Shipper |
| GET    | `/freight/shippers/{id}/smartway-audits`              | List SmartWay audits for a single shipper.                                         | BrokerOps, Shipper        |
| POST   | `/freight/_clock/set_current_utc`                     | Test-driving: pin the server's current_utc to a literal ISO 8601 timestamp.       | BrokerOps                 |
| POST   | `/freight/_clock/advance`                             | Test-driving: trigger system-time-driven auto-transitions on the pinned clock.    | BrokerOps                 |

## 5. Error Code Catalogue

The table below enumerates every error identifier returned by this API together with its HTTP status code. The condition that triggers each error is established in the relevant §2 or §3 narrative — readers reconstruct trigger conditions from those subsections rather than from this table.

| Error ID                          | HTTP Status Code |
| --------------------------------- | ---------------- |
| `ERR_UNAUTHENTICATED`             | 401              |
| `ERR_UNAUTHORIZED`                | 403              |
| `ERR_RESOURCE_NOT_FOUND`          | 404              |
| `ERR_FK_NOT_FOUND`                | 422              |
| `ERR_INVALID_STATE`               | 409              |
| `ERR_STALE_VERSION`               | 412              |
| `ERR_SAFETY_SCORE_TOO_HIGH`       | 422              |
| `ERR_INSURANCE_EXPIRED`           | 422              |
| `ERR_SMARTWAY_INELIGIBLE`         | 422              |
| `ERR_CONTRACT_RATE_STALE`         | 422              |
| `ERR_TIME_WINDOW_INVALID`         | 422              |
| `ERR_DELIVERY_BEFORE_PICKUP`      | 422              |
| `ERR_CONTRACT_WINDOW_INVALID`     | 422              |
| `ERR_INVALID_MC_USDOT`            | 422              |
| `ERR_DISPUTE_AMOUNT_EXCEEDS_OPEN` | 422              |
| `ERR_RESOLUTION_AMOUNT_INVALID`   | 422              |
| `ERR_CREDIT_LIMIT_EXCEEDED`       | 422              |
| `ERR_PAYMENT_OVERAGE`             | 422              |
| `ERR_FACTORING_FEE_BELOW_MIN`     | 422              |
| `ERR_AUDIT_QUARTER_INVALID`       | 422              |
| `ERR_INVALID_REQUEST`             | 400              |
| `ERR_CONTRACT_WINDOW_OVERLAP`     | 422              |
| `ERR_QUOTE_WINDOW_OVERLAP`        | 422              |
