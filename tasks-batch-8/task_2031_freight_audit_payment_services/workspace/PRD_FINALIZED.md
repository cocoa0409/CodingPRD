# Freight Audit Payment API — Product Requirements Document

## 1. Introduction

Freight invoices are unreliable billing documents: carriers bill accessorial services that were never rendered, apply stale rates after a contract has renewed, and occasionally bill the same shipment twice. A freight audit provider exists to catch exactly this leakage on behalf of its shipper clients. This document specifies the Freight Audit & Payment Services API — the platform the provider operates to capture carrier invoices, match every line against the negotiated rate contract that was in force, route discrepancies into structured carrier disputes, allocate audited cost to general-ledger accounts and business units, and schedule payment with full remittance visibility back to the carrier.

The platform treats money as something to be proven, not assumed. Every invoice carries two independent status dimensions — an audit dimension that walks from receipt through rating to clearance or exception, and a payment dimension that walks from unpaid through scheduling to settlement — and every monetary comparison is decided against per-client tolerances expressed in absolute minor units and in basis points. Multi-country operation is first-class: carriers bill in their own currencies, clients report savings in a home currency, and all conversion runs through explicit, dated exchange-rate records. Overcharges that survive all the way to payment are clawed back through recovery claims, and a checksummed analytics export feeds the client's transportation reporting. A logical clock governs every date-sensitive rule, optimistic concurrency guards the two composition-heavy writes, and segregation of duties keeps payment composition strictly separate from payment release.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, representations, and evaluation order that apply to every endpoint under the `/fap` mount.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The platform recognizes seven roles. `FapAdmin` is the audit provider's platform administrator, responsible for client onboarding, carrier and contract master data, the logical clock and daily sweeps, and force-resolution of escalated disputes. `AuditAnalyst` is the provider's audit operator, handling shipment intake, invoice capture, rating and finalization, exception negotiation, and recovery-claim drafting. `FinanceController` is the provider's finance operator, owning GL master data and coding, cost allocations, exchange rates, payment-run composition, recovery collection, and analytics exports. `TreasuryApprover` is the payment release and settlement authority. `CarrierRep` is a carrier-side representative who answers disputes and acknowledges remittances. `ClientViewer` is a shipper-side read-only user. `System` is the automation identity under which sweeps and system transitions run. Any attempt to perform an operation outside the actor's role is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

The meaning of `X-User-ID` depends on the role. For `FapAdmin`, `AuditAnalyst`, `FinanceController`, `TreasuryApprover`, and `System`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `created_by_user_id` or `locked_by_user_id` on a payment run — but never compares it against any entity's `id`. When `X-User-Role` is `CarrierRep`, `X-User-ID` is the `id` of the acting Carrier: ownership checks on any resource that references a carrier compare the resource's `carrier_id` field to `X-User-ID`, and reads targeted at resources belonging to a different carrier are answered with `ERR_NOT_FOUND`. When `X-User-Role` is `ClientViewer`, `X-User-ID` is the `id` of the acting ClientAccount: reads are confined to resources whose `client_id` equals `X-User-ID`, and cross-client reads likewise return `ERR_NOT_FOUND`, so one tenant's data is never revealed to another.

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

List endpoints paginate through two query parameters. `limit` caps the number of returned items; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` skips a number of items from the start of the result set and defaults to 0. Unless stated otherwise, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of list responses carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Business Dates

Every date-sensitive decision in the platform — contract activation timestamps, dispute-window arithmetic, payment-run date validation, daily sweeps — reads a server-maintained **logical clock**, never the wall clock. Before any call, the logical clock reads exactly 2026-08-01T00:00:00Z; this is the startup default and the server never falls back to wall-clock time. A `FapAdmin` advances the clock through a test-driving capability that accepts a `to_iso8601` timestamp and answers with the new value as `current_utc`. Business dates such as `ship_date`, `invoice_date`, `effective_from`, `effective_to`, `effective_date`, `run_date`, `due_date`, and `opened_date` are calendar dates rendered as YYYY-MM-DD strings; wherever this document compares such a date against "the current logical date", it means the date portion of the logical clock.

### 2.5. Common Resource Properties

Every resource in the system — client accounts, carriers, rate contracts, shipment records, carrier invoices, invoice lines, audit exceptions, GL accounts, cost allocations, payment runs, payment run items, remittance advices, exchange rates, recovery claims, and analytics exports — carries the same four system-managed properties:

- `id`: a server-minted UUID, formatted without any type prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at`: an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version`: an integer that increments by one on every mutation, including mutations driven by cascades that originate on other resources.

### 2.6. Monetary Representation: Minor Units, Basis Points, and Rounding

All monetary amounts are integers denominated in the **minor units** of the relevant currency (cents, pence, sen, and so on) — decimal fractions never appear in amounts. Every rounding a calculation performs is **round half up** to whole minor units, applied at exactly the step the rule designates; multi-step calculations round at each designated step rather than only at the end. Relative thresholds and percentages are expressed in **basis points**, where 10000 basis points equal one hundred percent. Exchange rates are expressed in **parts per million** in the `rate_ppm` field: a converted amount equals the source amount multiplied by `rate_ppm` and divided by one million, rounded half up to a whole minor unit.

### 2.7. Nested Resource Retrieval and Referential Scope

Although several resources are created under a parent scope (a carrier under a client, a rate contract under a carrier), every resource is addressable by its own `id` once created. When an endpoint path contains more than one identifier, the server validates the identifiers strictly left to right: the first identifier that does not correspond to an existing resource is answered with `ERR_NOT_FOUND` (HTTP 404), and no later identifier is examined. Identifiers supplied inside a request body — a `carrier_id` on invoice intake, a `gl_account_id` on a coding action, an `invoice_id` on a payment-run item — must likewise exist and must belong to the same client as the enclosing scope; a dangling or cross-client reference is answered with `ERR_NOT_FOUND` as well.

### 2.8. Request Evaluation Order

Every request passes through a fixed evaluation pipeline, and a failure at any stage short-circuits the stages after it — when several rules would independently reject the same request, the earliest stage's error is the one reported. The stages, in order:

1. **Identity headers.** Presence and well-formedness of `X-User-ID` and `X-User-Role`; failures yield `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Role authorization and scope.** The role must be permitted on the endpoint, and entity-backed roles must act inside their own scope; failures yield `ERR_FORBIDDEN_FOR_ROLE`, except that out-of-scope reads by a `CarrierRep` or `ClientViewer` surface as `ERR_NOT_FOUND`.
3. **Existence.** Path identifiers are resolved left to right, and request-body references are checked for existence and same-client membership; failures yield `ERR_NOT_FOUND`.
4. **Optimistic concurrency.** On the version-guarded writes (see §2.9), the supplied expected version must match the parent entity's current `version`; a mismatch yields `ERR_STALE_VERSION` (HTTP 412).
5. **Client lifecycle gate.** Business mutations on a client's resources require the client to be `ACTIVE`; failures yield `ERR_CLIENT_NOT_ACTIVE` (HTTP 409). The gate applies to every mutating operation under a client scope except the client lifecycle transitions themselves and the logical clock.
6. **State legality.** The target resource must be in a state that permits the requested transition; failures yield `ERR_INVALID_STATE` (HTTP 409). Request-shape failures — a malformed body, a missing required field, an unknown field, or an invalid enum value — are rejected as `ERR_INVALID_REQUEST` (HTTP 400) and are reported before any state-evaluation failure is surfaced.
7. **Segregation of duties.** Payment-run release is denied when the acting operator created or locked the run; failures yield `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).
8. **Temporal windows.** Contract window sanity (`ERR_CONTRACT_WINDOW_INVALID`, HTTP 422), contract window overlap (`ERR_CONTRACT_WINDOW_OVERLAP`, HTTP 409), the dispute window (`ERR_DISPUTE_WINDOW_EXPIRED`, HTTP 409), and payment-run dates (`ERR_RUN_DATE_PAST`, HTTP 409) — enforced on contract creation and activation, on exception notification and carrier response, and on payment-run creation respectively.
9. **Uniqueness and structural constraints.** Duplicate detection for PRO numbers, invoice numbers, and exchange rates (`ERR_DUPLICATE_PRO_NUMBER`, `ERR_DUPLICATE_INVOICE_NUMBER`, `ERR_DUPLICATE_FX_RATE`, all HTTP 409), weight-break ordering (`ERR_WEIGHT_BREAK_INVALID`, HTTP 422), allocation sums (`ERR_ALLOCATION_SUM_INVALID`, HTTP 422), and invoice line-total agreement (`ERR_AMOUNT_MISMATCH`, HTTP 422) — enforced on shipment creation, invoice creation, exchange-rate creation, GL account creation, contract activation, and allocation replacement.
10. **Referential status.** Referenced resources must be in a workable status: the carrier must be `ACTIVE` when payment is scheduled (`ERR_CARRIER_NOT_ACTIVE`), the GL account must be active when coded against (`ERR_GL_ACCOUNT_INACTIVE`), no live exception may block a rerate (`ERR_EXCEPTION_STILL_ACTIVE`), and the invoice must be payable for scheduling or write-off (`ERR_INVOICE_NOT_PAYABLE`) — guarding payment-run item composition, GL coding, allocations, invoice creation, rerating, and write-off.
11. **Fiscal amounts.** Amounts must be positive where required (`ERR_AMOUNT_INVALID`, HTTP 422); a concession credit may not exceed the disputed amount (`ERR_CREDIT_EXCEEDS_DISPUTED`); a claim may not exceed what was paid (`ERR_CLAIM_EXCEEDS_PAID`); a recovery may not exceed what was claimed (`ERR_RECOVERY_EXCEEDS_CLAIMED`); and a cross-currency scheduling step needs an exchange-rate path (`ERR_FX_RATE_MISSING`) — guarding invoice creation, exception resolution, recovery-claim creation and collection, and payment-run item composition.

### 2.9. Optimistic Concurrency Control

Two writes compose state that other actors may be reading, so both are guarded by optimistic concurrency. Activating a rate contract (`POST /fap/rate-contracts/{id}/activate`) requires the request to carry `expected_rate_contract_version`, the caller's last observed `version` of the contract; if the contract's current `version` no longer matches — activation both bumps the version and may unleash the supersede and re-rating cascade, so a writer holding an older observed version is acting on stale state — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Composing a payment run (`POST /fap/payment-runs/{id}/items`, and the run's automatic fill via `POST /fap/payment-runs/{id}/auto_fill`) likewise requires `expected_payment_run_version` matching the run's current `version`; each successful composition step increments the run's `version` by one, so a caller batching items from an older observed version is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than silently building on state it has not seen. Endpoints not named here accept no version field.

### 2.10. Client Lifecycle Gating and Cross-Entity Cascades

A client account is the commercial container for everything else in the system, and its lifecycle gates all business traffic: while a client is not `ACTIVE`, business mutations on its carriers, contracts, shipments, invoices, ledger codes, exchange rates, payment runs, claims, and exports are refused (stage 5 above), and activation is what unlocks them. Several single requests deliberately mutate more than one aggregate in ordered cascade hops — contract activation can supersede a predecessor and re-rate affected invoices; releasing a payment run advances its items and their invoices and spawns remittance advices; settling a run advances invoices, shipments, and advices. Every resource touched by a cascade is mutated in its own right: its `updated_at` refreshes and its `version` increments per §2.5. Where a transition needs a compensating reverse path — unlocking a payment run deletes its items and zeroes its totals — the compensation is part of the same contract and is described together with the transition it reverses.

## 3. Business Logic & Workflows

### 3.1. Client Onboarding and Account Lifecycle

Everything begins when a `FapAdmin` registers a shipper client with its display `name`, its `home_country` as an ISO 3166-1 alpha-2 code, and its `home_currency` as an ISO 4217 code — the currency in which savings are reported and into which foreign-currency amounts are converted for reporting. Three audit policies ride on the account, each with a default the creation call can override: `audit_tolerance_minor` (default 500) is the absolute variance, in home-currency minor units, up to which an invoice's audit variance auto-clears; `audit_tolerance_pct_bp` (default 200) is the same tolerance expressed in basis points of the rated total; and `dispute_window_days` (default 30) is the number of days an audit exception may remain unresolved before the system expires it.

A new account starts in `ONBOARDING`. Activation by a `FapAdmin` moves it to `ACTIVE`, which is what makes business mutations on the client's resources available; the same activation also reverses a suspension (`SUSPENDED` → `ACTIVE`). Suspension moves `ACTIVE` → `SUSPENDED`. Termination moves `ACTIVE` → `TERMINATED`, the terminal state, and is only granted to a settled ledger: the account's `outstanding_liability_minor` must be zero and no invoice may remain with `payment_status` `UNPAID` or `SCHEDULED`; otherwise termination is refused with `ERR_CLIENT_NOT_SETTLED`.

Two computed rollups ride on the account and are derivable on demand: `savings_realized_minor` and `outstanding_liability_minor`, both defined in §3.9. A dedicated savings read returns both along with their components. Separately, an operations sweep — runnable by `FapAdmin` or the `System` identity — expires the client's overdue contracts and dispute exceptions and reports what it touched as `expired_contract_ids` and `expired_exception_ids`; the two expiry rules themselves live with contracts (§3.2) and exceptions (§3.5).

### 3.2. Carrier Onboarding and Rate Contract Management

Carriers are onboarded per client by a `FapAdmin`, who supplies the carrier's `scac_code` (its Standard Carrier Alpha Code), `legal_name`, domicile `country`, the `billing_currency` it invoices in, an optional `payment_terms_days` (default 30) that later determines invoice due dates, and a `remit_email` where remittance advices are delivered. A carrier starts `PENDING_ONBOARD`; onboarding approval moves it to `ACTIVE`. Suspending moves `ACTIVE` → `SUSPENDED`, reinstating reverses it (`SUSPENDED` → `ACTIVE`), and offboarding moves either `ACTIVE` or `SUSPENDED` → `OFFBOARDED` — but only once the carrier holds no invoice with `payment_status` `UNPAID` or `SCHEDULED`; open invoices block offboarding with `ERR_CARRIER_HAS_OPEN_INVOICES`.

Rate contracts are drafted against a carrier. The draft carries a `name`, the `currency` every lane rate is denominated in, a half-open validity window running from `effective_from` (inclusive) to `effective_to` (exclusive), an optional `supersedes_contract_id` declaring which currently `ACTIVE` contract this one replaces upon activation, and the `lanes` array. Each lane names an `origin_country`, a `dest_country`, and a `mode`; a `weight_breaks` list whose entries each pair a `min_kg` threshold with a `rate_per_kg_minor`; a `fuel_surcharge_pct_bp`; an `accessorials` list whose entries each pair a service `code` with a `flat_minor` fee and a `cap_pct_bp`; and a `minimum_charge_minor` floor for the lane. Contracts are born `DRAFT`, and a draft that will never be used can be discarded (`DRAFT` → `DISCARDED`).

Activation is the contract's guarded write and the platform's most consequential single transition. The checks run in the global evaluation order of §2.8: the optimistic-concurrency check on `expected_rate_contract_version` fires before any business rule; the window sanity rule then requires `effective_from` strictly earlier than `effective_to` (`ERR_CONTRACT_WINDOW_INVALID`) — the same sanity rule is also enforced when the draft is first created; the overlap rule rejects activation with `ERR_CONTRACT_WINDOW_OVERLAP` when the contract's half-open window would intersect another `ACTIVE` contract of the same carrier that covers an intersecting lane, unless that other contract is the declared supersedes target; and every lane's `weight_breaks` must be strictly ascending by `min_kg` (`ERR_WEIGHT_BREAK_INVALID`). On success the contract moves `DRAFT` → `ACTIVE`, `activated_at` — which remains unset while the contract is a draft — is stamped with the current logical clock, and the contract's `version` increments by one.

When the activated contract names a `supersedes_contract_id`, activation cascades in three hops. Hop one: the named contract moves from `ACTIVE` to `SUPERSEDED`. Hop two: every carrier invoice whose `rated_contract_id` points at the superseded contract and whose `audit_status` is `RATED` or `EXCEPTION` is re-rated against the newly active contract — line rating recomputes each line's `rated_amount_minor` and the invoice's `rated_total_minor`, `variance_minor`, and `variance_pct_bp`, and `rated_contract_id` is updated to the new contract. Hop three: every audit exception in `OPEN`, `CARRIER_NOTIFIED`, or `CARRIER_RESPONDED` with code `RATE_MISMATCH` on one of those re-rated invoices is re-evaluated against the client's tolerances; when the new absolute variance is within `audit_tolerance_minor` and the new `variance_pct_bp` is within `audit_tolerance_pct_bp`, the exception auto-transitions to `RESOLVED_ACCEPTED` with `resolution_credit_minor` set to its `disputed_amount_minor`, and the invoice's `approved_amount_minor` is pinned to the new `rated_total_minor`.

Two system paths retire contracts without a supersedor. The daily sweep expires every `ACTIVE` contract whose `effective_to` is on or before the current logical date, moving it to `EXPIRED`. Both retirement states are terminal alongside `DISCARDED`: `SUPERSEDED`, `EXPIRED`, and `DISCARDED` end the lifecycle. A `SUPERSEDED` contract nevertheless remains eligible when historical invoices are rated (§3.4); `EXPIRED` and `DISCARDED` contracts do not.

### 3.3. Shipment Registration and Invoice Intake

An `AuditAnalyst` registers the shipment facts that invoices will later be matched against: the hauling `carrier_id`, the `pro_number`, the `ship_date`, the `origin_country` and `dest_country`, the `mode` (one of `PARCEL`, `LTL`, `FTL`, `AIR`, `OCEAN`), the `actual_weight_kg`, and optionally `accessorials_rendered`, the list of accessorial service codes actually performed. A PRO number is unique per client and carrier among shipments that have not been voided: reusing a live one fails with `ERR_DUPLICATE_PRO_NUMBER`. New shipments are `REGISTERED`. Voiding moves `REGISTERED` → `VOIDED` and is allowed only while no non-voided invoice references the shipment — attempting it otherwise fails with `ERR_INVALID_STATE` — and voiding releases the PRO number back into the uniqueness scope. Two system-driven transitions complete the shipment's life: when an invoice referencing the shipment completes capture, the shipment moves `REGISTERED` → `INVOICED`; and when the referencing invoice settles, an `INVOICED` shipment moves to `CLOSED` (§3.8). Both `CLOSED` and `VOIDED` are terminal.

Invoice intake mirrors what the carrier actually billed. The `AuditAnalyst` presents the invoicing `carrier_id`, the carrier's `invoice_number`, the `invoice_date`, the invoice `currency`, the `billed_total_minor`, the `lines` array — each line carrying a `charge_code` drawn from `BASE_FREIGHT`, `FUEL_SURCHARGE`, `LIFTGATE`, `RESIDENTIAL`, `INSIDE_DELIVERY`, `DETENTION`, `STORAGE`, or `OTHER`, together with its `billed_amount_minor` — and optionally a `shipment_id` linking the invoice to a registered shipment. Intake enforces four shape rules before anything is stored: the invoice `currency` must equal the invoicing carrier's `billing_currency`; the `invoice_number` must not repeat another non-voided invoice of the same client and carrier (`ERR_DUPLICATE_INVOICE_NUMBER`, and this exact-duplicate rejection happens at creation time, before the invoice ever reaches capture); `billed_total_minor` must equal the sum of the lines' billed amounts (`ERR_AMOUNT_MISMATCH`); and amounts must be positive where a positive amount is required (`ERR_AMOUNT_INVALID`). A linked shipment must not be `VOIDED`. On acceptance, each entry of `lines` materializes as an invoice-line row of the invoice, and the invoice is born with its two parallel status dimensions: `audit_status` `RECEIVED` and `payment_status` `UNPAID`. The computed fields start dormant — `rated_total_minor` is 0 until a rating pass runs, `duplicate_flag` is only assigned during capture, and `variance_minor`, `variance_pct_bp`, `approved_amount_minor`, `home_total_minor`, `due_date`, `scheduled_minor`, and `paid_minor` take their values from the audit and payment events described below.

Capture (`RECEIVED` → `CAPTURED`) is an `AuditAnalyst` action and requires the owning client to be `ACTIVE`, failing with `ERR_CLIENT_NOT_ACTIVE` otherwise. Capture runs fuzzy duplicate detection against every other non-voided invoice of the same client and carrier: the invoice is flagged `FUZZY` when there exists another such invoice whose billed total differs from the new invoice's `billed_total_minor` by an amount that, multiplied by ten thousand, does not exceed fifty times the new invoice's billed total (with the new invoice's total treated as 1 if it were zero) **and** whose `invoice_date` lies at most seven days away from the new invoice's `invoice_date`, both ends of that window inclusive; otherwise the flag is set to `NONE`. Both fuzzy boundaries are inclusive. Capture also advances a linked shipment from `REGISTERED` to `INVOICED`.

An invoice that should never have entered the system can be voided while it is `RECEIVED` or `CAPTURED`, moving it to audit status `VOIDED`, terminal on the audit dimension; voiding releases the `invoice_number` back into the uniqueness scope so a corrected invoice may reuse it.

### 3.4. Contract Rating and Audit Finalization

Rating (`CAPTURED` → `RATED`) is performed by an `AuditAnalyst` and may carry an optional `policy`: `SHIP_DATE`, the default when the request omits `policy`, rates as of the shipment's `ship_date` so historical contract terms apply; `INVOICE_DATE` rates as of the invoice's `invoice_date`, under which a later-superseding contract with lower rates yields a different `rated_total_minor` for identical lines. The contract selector considers the carrier's contracts in `ACTIVE` or `SUPERSEDED` status whose half-open window contains the as-of date and picks the one with the latest `activated_at`, breaking ties by latest `created_at`. When no contract covers the date, no rating happens at all: the invoice instead moves `CAPTURED` → `EXCEPTION`, and the system opens an audit exception with code `NO_CONTRACT`, a `disputed_amount_minor` equal to the full `billed_total_minor`, and routing to the `AUDIT_TEAM` queue.

Lane matching keys on the shipment: a lane matches when its `origin_country`, `dest_country`, and `mode` equal the shipment's. A `BASE_FREIGHT` line can only be rated against a linked shipment, because both the lane and the weight tier come from it; when the invoice carries no `shipment_id`, or no lane matches the shipment, the lane is treated as missing — the platform never assumes billed equals rated as a zero-variance pass-through — and the invoice is handled exactly like the no-contract case above, routing to `EXCEPTION` with `NO_CONTRACT`.

With a lane in hand, each line is rated in the invoice's currency, rounding half up to whole minor units at each step. For `BASE_FREIGHT`, the applicable tier is the last weight break whose `min_kg` is less than or equal to the shipment's `actual_weight_kg`; the base amount is that tier's `rate_per_kg_minor` multiplied by `actual_weight_kg`; the rated amount is the greater of the base amount and the lane's `minimum_charge_minor`. For `FUEL_SURCHARGE`, the rated amount is the rated base-freight amount multiplied by the lane's `fuel_surcharge_pct_bp` and divided by ten thousand, rounded half up. For an accessorial line (`LIFTGATE`, `RESIDENTIAL`, `INSIDE_DELIVERY`, `DETENTION`, `STORAGE`): when the lane's `accessorials` do not offer that code, or the shipment's `accessorials_rendered` do not include it, the rated amount is 0 and the line is flagged as an invalid accessorial; otherwise the rated amount is the smaller of the accessorial's `flat_minor` and the rated base-freight amount multiplied by its `cap_pct_bp` and divided by ten thousand, rounded half up. An `OTHER` line is uncontested: its rated amount equals its `billed_amount_minor`. Each line's result lands in `rated_amount_minor`, the invoice's `rated_total_minor` is the sum of the lines' rated amounts, `variance_minor` is the signed difference of `billed_total_minor` minus `rated_total_minor`, and `variance_pct_bp` is the absolute variance multiplied by ten thousand and divided by the rated total (by 1 when the rated total is zero), rounded down to a whole basis-point value. The contract used is recorded in `rated_contract_id`.

Finalization (`RATED` → `CLEARED`, or `RATED` → `EXCEPTION` when routing fails) is the audit's verdict. When any exception on the invoice already stands at `RESOLVED_ACCEPTED` or `RESOLVED_CONCEDED`, the invoice clears and the resolution's pinned amount governs `approved_amount_minor`. Otherwise the routing checks run in a strict precedence order and the first match wins: first, a `duplicate_flag` of `FUZZY` raises an exception with code `DUPLICATE_FUZZY`, a `disputed_amount_minor` equal to the full `billed_total_minor`, and routing to `AUDIT_TEAM`; second, any line flagged as an invalid accessorial raises `INVALID_ACCESSORIAL` with a disputed amount equal to the sum of the billed amounts of the invalid lines, routed to `CARRIER`; third, an absolute `variance_minor` exceeding the client's `audit_tolerance_minor` **or** a `variance_pct_bp` exceeding the client's `audit_tolerance_pct_bp` raises `RATE_MISMATCH` with a disputed amount equal to the positive part of the variance (the variance itself when positive, zero otherwise), routed to `CARRIER`. Equality at either tolerance passes — a variance exactly at the tolerance clears rather than routes. When nothing matches, the invoice clears with `approved_amount_minor` equal to `billed_total_minor` minus the positive part of the variance: an overbilling is never paid, while an underbilling is paid as billed, not topped up.

Clearing also stamps the money facts. `home_total_minor` is computed through currency conversion at the invoice-date variant (§3.7): each line's approved share is converted and rounded individually, and only then are the per-line results summed — summing first and rounding once is a different number and is not an acceptable substitute. `due_date` is the `invoice_date` advanced by the carrier's `payment_terms_days`.

A rerate (`EXCEPTION` → `RATED`) by an `AuditAnalyst` re-runs the line rating — recomputing the rated totals and variances and refreshing `rated_contract_id` — and accepts the same optional `policy`. It is refused with `ERR_EXCEPTION_STILL_ACTIVE` while any exception on the invoice stands at `OPEN`, `CARRIER_NOTIFIED`, `CARRIER_RESPONDED`, or `ESCALATED`; resolved or expired exceptions do not block it.

### 3.5. Dispute Exceptions and Carrier Negotiation

An audit exception records a single contested finding on an invoice: its `code` (`RATE_MISMATCH`, `DUPLICATE_FUZZY`, `INVALID_ACCESSORIAL`, or `NO_CONTRACT`), the `disputed_amount_minor` withheld from payment while the exception is open, a `resolution_credit_minor` that starts at 0, the `routed_queue` it was dispatched to, a `round_count` of counter offers that starts at 0, and the `opened_date` stamped from the logical clock on the day the exception was raised. Routing follows the code: `NO_CONTRACT` and `DUPLICATE_FUZZY` go to the `AUDIT_TEAM` queue, while `RATE_MISMATCH` and `INVALID_ACCESSORIAL` go to the `CARRIER` queue; `FINANCE` exists as a queue value for completeness of the model. Every exception is born `OPEN`, and the terminal states are `RESOLVED_ACCEPTED`, `RESOLVED_CONCEDED`, and `EXPIRED`.

The negotiation loop runs between the provider and the carrier. An `AuditAnalyst` notifies the carrier, moving `OPEN` → `CARRIER_NOTIFIED`, only while the dispute window is still open — the current logical date must not be later than `opened_date` plus the client's `dispute_window_days`, otherwise the action fails with `ERR_DISPUTE_WINDOW_EXPIRED`. A `CarrierRep` then answers, moving `CARRIER_NOTIFIED` → `CARRIER_RESPONDED`, optionally attaching a `response_note`; the acting carrier's identity must match the invoice's `carrier_id` (`ERR_FORBIDDEN_FOR_ROLE` otherwise), and the same dispute-window check applies with the same error. If the answer is unsatisfying, the `AuditAnalyst` counters, moving `CARRIER_RESPONDED` back to `CARRIER_NOTIFIED` and incrementing `round_count` by one. At most three counters are allowed: the counter succeeds while `round_count` is below three, so the third counter (moving the count from 2 to 3) still succeeds, but a fourth attempt fails with `ERR_NEGOTIATION_ROUND_LIMIT`.

Resolution pins the invoice's payable amount. Resolving with an `outcome` of `ACCEPT` moves `CARRIER_RESPONDED` → `RESOLVED_ACCEPTED`: the carrier concedes the full dispute, `resolution_credit_minor` is set to the full `disputed_amount_minor`, the invoice's `approved_amount_minor` is pinned to its `rated_total_minor`, and `home_total_minor` is recomputed. Resolving with an `outcome` of `CONCEDE` moves `CARRIER_RESPONDED` → `RESOLVED_CONCEDED`: the request carries a `credit_minor` that must not exceed the `disputed_amount_minor` (`ERR_CREDIT_EXCEEDS_DISPUTED`), `resolution_credit_minor` is set to that credit, the invoice's `approved_amount_minor` becomes `billed_total_minor` minus the credit, and `home_total_minor` is recomputed. At any point from `OPEN`, `CARRIER_NOTIFIED`, or `CARRIER_RESPONDED`, an `AuditAnalyst` may escalate the exception to `ESCALATED`. An escalated exception leaves the negotiation loop: only a `FapAdmin` can close it, by force-resolving `ESCALATED` → `RESOLVED_CONCEDED` under the same concession rule — a `credit_minor` not exceeding the disputed amount, with the same effects on `resolution_credit_minor`, `approved_amount_minor`, and `home_total_minor`.

Exceptions that outlive the dispute window expire through the daily sweep: when the current logical date is later than `opened_date` plus `dispute_window_days`, an exception in `OPEN`, `CARRIER_NOTIFIED`, or `CARRIER_RESPONDED` moves to `EXPIRED`. Expiry from `OPEN` additionally releases the disputed hold, while the invoice itself remains in audit status `EXCEPTION` until it is rerated; expiry from `CARRIER_NOTIFIED` or `CARRIER_RESPONDED` carries no further effect beyond the state change. `ESCALATED` exceptions are exempt from expiry — only a `FapAdmin` force-resolution closes them.

### 3.6. GL Coding and Cost Allocation

A `FinanceController` maintains the client's chart of accounts: each GL account carries a `code` unique within the client, the `business_unit` it rolls up to, the `country` of the account, and an `active` flag that defaults to true. Assigning a line's primary GL code writes the line's `gl_account_id`; an inactive account refuses new coding with `ERR_GL_ACCOUNT_INACTIVE`.

Beyond the primary code, each invoice line can be split across accounts through its allocation set. The replace-set action takes an `allocations` array in which every entry names a `gl_account_id` target and a `percentage_bp` share in basis points; the shares across the set must sum to exactly 10000 basis points, failing with `ERR_ALLOCATION_SUM_INVALID` otherwise. The amount being split is the line's `rated_amount_minor` when the invoice's `rated_total_minor` is greater than zero, and the line's `billed_amount_minor` when it is not. Each row's `allocated_minor` is that line amount multiplied by the row's `percentage_bp` and divided by ten thousand, rounded half up. Because per-row rounding can drift from the line amount, the remainder — the line amount minus the sum of the rounded rows, in either direction — is applied to the row with the largest `percentage_bp`; ties break by the target account's `code` in ascending order and then by the allocation row's `created_at` in ascending order. Repeating the action replaces the set wholesale: the prior rows are deleted and the split is recomputed from scratch, so allocations never drift across edits. Each resulting allocation row keeps its `invoice_line_id` back-reference to the line it splits alongside its `gl_account_id` target, `percentage_bp`, and computed `allocated_minor`. The allocation rows of a line, and the allocation rows targeting one GL account, are both readable.

### 3.7. Foreign Exchange Rates and Currency Conversion

Exchange rates are client-scoped master data maintained by a `FinanceController`. Each rate record names a `from_currency`, a `to_currency`, the `effective_date` from which it applies, the `rate_ppm` value in parts per million, and a `source` of `ECB` or `MANUAL`. One rate may exist per client, currency pair, and effective date; a duplicate is rejected with `ERR_DUPLICATE_FX_RATE`.

Conversion always resolves the rate the same way: among the client's rates with the matching `from_currency` and `to_currency` whose `effective_date` is on or before the as-of date, the one with the latest `effective_date` applies, ties broken by latest `created_at`. When no such rate exists, the operation that needed the conversion fails with `ERR_FX_RATE_MISSING`. The converted amount is the source amount multiplied by `rate_ppm` and divided by one million, rounded half up to a whole minor unit. Two as-of variants exist. The invoice-date variant — used for `home_total_minor` at finalization and for GL reporting amounts — reads the rate as of the invoice's `invoice_date`. The payment-date variant — used when a payment-run item's `scheduled_amount_minor` is computed into the run's currency — reads the rate as of the run's `run_date`, so a rate change between invoice date and run date legitimately yields a different amount for the same invoice. When source and target currency coincide, conversion is the identity and no rate record is needed.

Invoice-level home totals have a pinned evaluation order: each line's approved share is converted first and rounded individually, and the per-line results are then summed; summing first and rounding once at the end is the forbidden alternative. A line's approved share is its proportional share of the invoice's `approved_amount_minor` weighted by its `rated_amount_minor`; when the invoice's `rated_total_minor` is zero, the line's billed amount stands in as the weight.

### 3.8. Payment Runs, Remittance, and Settlement

A `FinanceController` opens a payment run with a `run_date`, a settlement `currency`, and an optional `country_scope` restricting which carrier countries automatic selection may draw from. The `run_date` must not lie before the current logical date (`ERR_RUN_DATE_PAST`). The run is born `DRAFT`, and the acting operator's identity is recorded in `created_by_user_id` for segregation of duties.

Items join the run in two ways, both guarded by `expected_payment_run_version` as described in §2.9. Adding a single item names an `invoice_id`; the invoice must be audit-`CLEARED` and payment-`UNPAID` (`ERR_INVOICE_NOT_PAYABLE`), its carrier must be `ACTIVE` (`ERR_CARRIER_NOT_ACTIVE`), and when the invoice currency differs from the run currency a covering exchange rate must exist (`ERR_FX_RATE_MISSING`). The item's `scheduled_amount_minor` is the invoice's `approved_amount_minor` converted to the run currency at the payment-date variant. Automatic fill instead sweeps the client's whole book: an invoice is eligible when it belongs to the run's client, is audit-`CLEARED` and payment-`UNPAID`, its carrier is `ACTIVE`, the run's `country_scope` is unset or matches the carrier's `country`, the invoice's `due_date` falls on or before the `run_date` plus seven days (inclusive), the invoice currency either equals the run currency or has an exchange-rate path into it, and the invoice is not already an item of any run in `DRAFT`, `LOCKED`, or `RELEASED`. Eligible invoices are added in `due_date` ascending order, ties broken by the invoice's `created_at` ascending; an empty eligible set adds zero items, which surfaces later when locking fails. Each successful composition step increments the run's `version`. Every item row carries its `payment_run_id` back-reference to the containing run alongside the `invoice_id` it schedules, and its `status` walks `SCHEDULED` → `RELEASED` → `PAID` as the run advances.

Locking (`DRAFT` → `LOCKED`) prices the run's early-settlement discount and requires at least one item (`ERR_EMPTY_PAYMENT_RUN`). The evaluation order is pinned to break the circularity between gross and discount: first `gross_total_minor` is the sum of the items' `scheduled_amount_minor`; then the discount tier is read off that pre-discount gross — a gross of at least 5,000,000 minor units earns 250 basis points, a gross of at least 1,000,000 earns 150 basis points, anything below earns none; then each item's `discount_minor` is its `scheduled_amount_minor` multiplied by the tier's basis points and divided by ten thousand, rounded half up; finally `discount_total_minor` is the sum of the item discounts and `total_minor` is `gross_total_minor` minus `discount_total_minor`. Reading the tier off the post-discount net would produce a different, wrong result. Locking records the acting operator in `locked_by_user_id`. Unlocking (`LOCKED` → `DRAFT`) is the compensation: every item is deleted and all three totals reset to zero. Because items only begin to affect invoices at release, an unlock normally has no invoice effects to reverse; the invoice payment dimension nonetheless defines the mirror compensation — if a covering item is ever deleted out from under a `SCHEDULED` invoice, the invoice returns to `UNPAID` and the removed item's `scheduled_amount_minor` is subtracted from its `scheduled_minor`, returning it to zero when the only item is removed.

Release (`LOCKED` → `RELEASED`) belongs to `TreasuryApprover` and enforces segregation of duties: the acting operator must be neither the run's `created_by_user_id` nor its `locked_by_user_id`, failing with `ERR_SEGREGATION_OF_DUTIES` otherwise. Release cascades in three hops. Hop one: every item moves `SCHEDULED` → `RELEASED`. Hop two, per item: the item's invoice moves from payment status `UNPAID` to `SCHEDULED`, and the item's `scheduled_amount_minor` is added to the invoice's `scheduled_minor` — the accumulator that tracks, in run currency, what is scheduled against the invoice in released runs. Hop three: one remittance advice is created per distinct carrier among the items, born `GENERATED`, with `total_minor` equal to the sum of each of that carrier's items' `scheduled_amount_minor` minus `discount_minor`, and `item_count` equal to the number of that carrier's items; advices are destined for the carrier's `remit_email`.

Settlement (`RELEASED` → `SETTLED`), again by `TreasuryApprover`, is where money is considered moved. Every item moves `RELEASED` → `PAID`. Per item, the invoice's `paid_minor` grows by the item's `scheduled_amount_minor` minus its `discount_minor`, in run currency; the invoice's payment status becomes `PAID` when the item's `discount_minor` is zero, and `SHORT_PAID` when a retained discount leaves it short. Every remittance advice of the run moves `GENERATED` → `SENT`. And every linked shipment still `INVOICED` moves to `CLOSED`. A run may also be cancelled while `DRAFT` (`DRAFT` → `CANCELLED`), deleting any items it holds; `SETTLED` and `CANCELLED` are terminal.

Two loose ends complete the payment story. A carrier acknowledges receipt of its remittance: a `CarrierRep` whose identity matches the advice's `carrier_id` moves the advice `SENT` → `ACKNOWLEDGED` (`ERR_FORBIDDEN_FOR_ROLE` otherwise). And a `FinanceController` may write off an invoice whose audit stands `CLEARED` while payment is still `UNPAID`, moving payment to `WRITTEN_OFF` (`ERR_INVOICE_NOT_PAYABLE` when the preconditions are unmet); a written-off invoice's approved amount is excluded from the client's `outstanding_liability_minor`.

### 3.9. Overcharge Recovery, Savings Reporting, and Analytics Export

When an overcharge is discovered only after payment, an `AuditAnalyst` drafts a recovery claim against the settled invoice, naming the `claimed_amount_minor` sought from the carrier and a `channel` of `CREDIT_MEMO`, `REFUND`, or `OFFSET`. Drafting requires the invoice's payment status to be `PAID` or `SHORT_PAID` (`ERR_INVALID_STATE` otherwise), and the claim may not exceed the invoice's `paid_minor` (`ERR_CLAIM_EXCEEDS_PAID`). The claim is born `DRAFTED` with `recovered_minor` at zero.

The claim lifecycle mirrors the dispute loop. Filing moves `DRAFTED` → `FILED`. The carrier answers through a `CarrierRep` whose identity matches the invoice's `carrier_id` (`ERR_FORBIDDEN_FOR_ROLE` otherwise): an `outcome` of `ACKNOWLEDGE` moves `FILED` → `ACKNOWLEDGED`, an `outcome` of `REBUT` moves `FILED` → `REBUTTED`. A rebutted claim can be filed again (`REBUTTED` → `FILED`) or given up; abandonment moves `DRAFTED`, `FILED`, or `REBUTTED` → `ABANDONED`. Collection is the finance act: a `FinanceController` collects an `ACKNOWLEDGED` claim into `COLLECTED`, recording the actual `recovered_minor`, which must not exceed the `claimed_amount_minor` (`ERR_RECOVERY_EXCEEDS_CLAIMED`). Collection feeds the savings rollup. `COLLECTED` and `ABANDONED` are terminal.

The savings read answers four numbers plus the reporting `currency`. `avoided_overcharge_minor` sums, over the client's invoices with payment status `PAID` or `SHORT_PAID`, the amount by which `billed_total_minor` exceeded `approved_amount_minor` (never below zero per invoice), converted to the home currency at the invoice-date variant — the identity when the invoice currency already is the home currency. `recovered_minor` sums the `recovered_minor` of the client's `COLLECTED` claims, converted at the invoice-date variant when the claim's invoice currency differs from home. `savings_realized_minor` is the sum of those two components. `outstanding_liability_minor` sums, over invoices audit-`CLEARED` with payment status `UNPAID` or `SCHEDULED`, the approved amount less whatever has already been settled against the invoice, expressed in home currency.

Finally, a `FinanceController` can pull the transportation analytics feed: an export request names an inclusive `date_from` and `date_to` bounding `invoice_date` — a `date_to` earlier than `date_from` is rejected with `ERR_EXPORT_RANGE_INVALID` — and an optional `include_statuses` list filtering by `audit_status`, where omitting it means all statuses. The export completes synchronously at creation, moving `REQUESTED` → `COMPLETED`: `row_count` counts the invoices in range (after the status filter), and `checksum` is the literal string `sha256:` followed by the SHA-256 hexadecimal digest of the comma-joined invoice numbers, ordered by each invoice's `created_at` ascending and then `invoice_number` ascending. `FAILED` stands as a terminal state of the export model, though the synchronous flow lands in `COMPLETED` at creation.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; all other operations — reads, state transitions, and mutations of existing resources — return `200 OK`. Where the Authorized Role(s) column reads "All roles", the endpoint admits exactly `FapAdmin`, `AuditAnalyst`, `FinanceController`, `TreasuryApprover`, `CarrierRep`, and `ClientViewer`, with `CarrierRep` and `ClientViewer` remaining scope-limited per §2.1. The table is deliberately minimal: request payloads, response shapes, and side effects are specified in the narratives of §2 and §3, not here. List endpoints accept the pagination parameters of §2.3 plus resource-specific filters: carriers by `client_id` and `status`; rate contracts by `client_id`, `carrier_id`, `supersedes_contract_id`, and `status`; shipments by `client_id`, `carrier_id`, and `status`; invoices by `client_id`, `carrier_id`, `shipment_id`, `rated_contract_id`, `audit_status`, and `payment_status`; invoice lines by `invoice_id` and `gl_account_id`; a client's exceptions by `status`; GL accounts by `client_id`; a client's exchange rates by `from_currency` and `to_currency`; payment runs by `client_id` and `status`; and a client's recovery claims by `status`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/fap/_clock/set_current_utc` | Set the logical clock | FapAdmin |
| POST | `/fap/clients` | Create a client account (status ONBOARDING) | FapAdmin |
| GET | `/fap/clients` | List client accounts (paginated) | All roles |
| GET | `/fap/clients/{id}` | Get a client account | All roles |
| POST | `/fap/clients/{id}/activate` | Activate client (ONBOARDING or SUSPENDED -> ACTIVE) | FapAdmin |
| POST | `/fap/clients/{id}/suspend` | Suspend client (ACTIVE -> SUSPENDED) | FapAdmin |
| POST | `/fap/clients/{id}/terminate` | Terminate client (ACTIVE -> TERMINATED); requires settled ledger | FapAdmin |
| GET | `/fap/clients/{id}/savings` | Computed savings rollup read | All roles |
| POST | `/fap/clients/{id}/run_daily_sweep` | Ops sweep: expire overdue contracts and dispute exceptions | FapAdmin, System |
| POST | `/fap/clients/{id}/carriers` | Create carrier (PENDING_ONBOARD) | FapAdmin |
| GET | `/fap/carriers` | List carriers | All roles |
| GET | `/fap/carriers/{id}` | Get a carrier | All roles |
| POST | `/fap/carriers/{id}/approve_onboard` | PENDING_ONBOARD -> ACTIVE | FapAdmin |
| POST | `/fap/carriers/{id}/suspend` | ACTIVE -> SUSPENDED | FapAdmin |
| POST | `/fap/carriers/{id}/reinstate` | SUSPENDED -> ACTIVE | FapAdmin |
| POST | `/fap/carriers/{id}/offboard` | ACTIVE or SUSPENDED -> OFFBOARDED; blocked while open invoices exist | FapAdmin |
| POST | `/fap/carriers/{id}/rate-contracts` | Create rate contract (DRAFT) | FapAdmin |
| GET | `/fap/rate-contracts` | List rate contracts | All roles |
| GET | `/fap/rate-contracts/{id}` | Get a rate contract | All roles |
| POST | `/fap/rate-contracts/{id}/activate` | DRAFT -> ACTIVE with OCC and supersede/re-rate cascade | FapAdmin |
| POST | `/fap/rate-contracts/{id}/discard` | DRAFT -> DISCARDED | FapAdmin |
| POST | `/fap/clients/{id}/shipments` | Register a shipment fact | AuditAnalyst |
| GET | `/fap/shipments` | List shipments | All roles |
| GET | `/fap/shipments/{id}` | Get a shipment | All roles |
| POST | `/fap/shipments/{id}/void` | REGISTERED -> VOIDED | AuditAnalyst |
| POST | `/fap/clients/{id}/invoices` | Capture a carrier invoice with its lines (audit RECEIVED, payment UNPAID) | AuditAnalyst |
| GET | `/fap/invoices` | List invoices | All roles |
| GET | `/fap/invoices/{id}` | Get an invoice | All roles |
| POST | `/fap/invoices/{id}/capture` | RECEIVED -> CAPTURED; runs duplicate detection | AuditAnalyst |
| POST | `/fap/invoices/{id}/rate` | CAPTURED -> RATED (or EXCEPTION with NO_CONTRACT when no covering contract) | AuditAnalyst |
| POST | `/fap/invoices/{id}/finalize_audit` | RATED -> CLEARED or RATED -> EXCEPTION per exception routing | AuditAnalyst |
| POST | `/fap/invoices/{id}/rerate` | EXCEPTION -> RATED; requires no active exceptions | AuditAnalyst |
| POST | `/fap/invoices/{id}/void` | RECEIVED or CAPTURED -> VOIDED | AuditAnalyst |
| POST | `/fap/invoices/{id}/write_off` | Payment UNPAID -> WRITTEN_OFF (requires audit CLEARED) | FinanceController |
| GET | `/fap/invoice-lines` | List invoice lines | All roles |
| GET | `/fap/invoice-lines/{id}` | Get an invoice line | All roles |
| GET | `/fap/invoices/{id}/lines` | List lines of an invoice | All roles |
| POST | `/fap/invoice-lines/{id}/gl-code` | Assign primary GL account to a line | FinanceController |
| POST | `/fap/invoice-lines/{id}/allocations` | Replace the line's cost-allocation set (must sum to 10000 bp) | FinanceController |
| GET | `/fap/invoice-lines/{id}/allocations` | List cost allocations of a line | All roles |
| GET | `/fap/invoices/{id}/exceptions` | List exceptions of an invoice | All roles |
| GET | `/fap/clients/{id}/exceptions` | List exceptions of a client | All roles |
| POST | `/fap/exceptions/{id}/notify_carrier` | OPEN -> CARRIER_NOTIFIED | AuditAnalyst |
| POST | `/fap/exceptions/{id}/carrier_respond` | CARRIER_NOTIFIED -> CARRIER_RESPONDED (carrier-scoped) | CarrierRep |
| POST | `/fap/exceptions/{id}/counter` | CARRIER_RESPONDED -> CARRIER_NOTIFIED; round_count +1, max 3 | AuditAnalyst |
| POST | `/fap/exceptions/{id}/resolve` | Resolve (ACCEPT from CARRIER_RESPONDED; CONCEDE from CARRIER_RESPONDED or, by FapAdmin, ESCALATED) | AuditAnalyst, FapAdmin |
| POST | `/fap/exceptions/{id}/escalate` | OPEN, CARRIER_NOTIFIED, or CARRIER_RESPONDED -> ESCALATED | AuditAnalyst |
| POST | `/fap/clients/{id}/gl-accounts` | Create GL account | FinanceController |
| GET | `/fap/gl-accounts` | List GL accounts | All roles |
| GET | `/fap/gl-accounts/{id}` | Get a GL account | All roles |
| GET | `/fap/gl-accounts/{id}/cost-allocations` | List cost allocations targeting a GL account | All roles |
| POST | `/fap/clients/{id}/fx-rates` | Create FX rate (unique per client, pair, and date) | FinanceController |
| GET | `/fap/clients/{id}/fx-rates` | List FX rates of a client | All roles |
| POST | `/fap/clients/{id}/payment-runs` | Create payment run (DRAFT); run_date not in the past | FinanceController |
| GET | `/fap/payment-runs` | List payment runs | All roles |
| GET | `/fap/payment-runs/{id}` | Get a payment run | All roles |
| POST | `/fap/payment-runs/{id}/items` | Add one item by invoice_id; OCC-guarded | FinanceController |
| POST | `/fap/payment-runs/{id}/auto_fill` | Add one item per eligible invoice per selection ranking; OCC-guarded | FinanceController |
| GET | `/fap/payment-runs/{id}/items` | List items of a run | All roles |
| GET | `/fap/invoices/{id}/payment-run-items` | List run items covering an invoice | All roles |
| POST | `/fap/payment-runs/{id}/lock` | DRAFT -> LOCKED; computes discount tiers | FinanceController |
| POST | `/fap/payment-runs/{id}/unlock` | LOCKED -> DRAFT; deletes items and zeroes totals | FinanceController |
| POST | `/fap/payment-runs/{id}/release` | LOCKED -> RELEASED; segregation of duties; cascades to items, invoices, advices | TreasuryApprover |
| POST | `/fap/payment-runs/{id}/settle` | RELEASED -> SETTLED; pays items, advances invoices, sends advices | TreasuryApprover |
| POST | `/fap/payment-runs/{id}/cancel` | DRAFT -> CANCELLED | FinanceController |
| GET | `/fap/payment-runs/{id}/remittance-advices` | List remittance advices of a run | All roles |
| GET | `/fap/carriers/{id}/remittance-advices` | List remittance advices of a carrier | All roles |
| POST | `/fap/remittance-advices/{id}/acknowledge` | SENT -> ACKNOWLEDGED (carrier-scoped) | CarrierRep |
| POST | `/fap/invoices/{id}/recovery-claims` | Draft a recovery claim on a PAID or SHORT_PAID invoice | AuditAnalyst |
| GET | `/fap/clients/{id}/recovery-claims` | List recovery claims of a client | All roles |
| GET | `/fap/invoices/{id}/recovery-claims` | List recovery claims of an invoice | All roles |
| POST | `/fap/recovery-claims/{id}/file` | DRAFTED or REBUTTED -> FILED | AuditAnalyst |
| POST | `/fap/recovery-claims/{id}/carrier_respond` | FILED -> ACKNOWLEDGED (ACKNOWLEDGE) or REBUTTED (REBUT); carrier-scoped | CarrierRep |
| POST | `/fap/recovery-claims/{id}/collect` | ACKNOWLEDGED -> COLLECTED | FinanceController |
| POST | `/fap/recovery-claims/{id}/abandon` | DRAFTED, FILED, or REBUTTED -> ABANDONED | AuditAnalyst |
| POST | `/fap/clients/{id}/analytics-exports` | Create analytics export; completes synchronously with row_count and checksum | FinanceController |
| GET | `/fap/clients/{id}/analytics-exports` | List analytics exports of a client | All roles |

## 5. Error Code Catalogue

Trigger conditions for each error live in the narratives of §2 and §3; this catalogue is only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_CLIENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_CLIENT_NOT_SETTLED` | 409 Conflict |
| `ERR_CARRIER_NOT_ACTIVE` | 409 Conflict |
| `ERR_CARRIER_HAS_OPEN_INVOICES` | 409 Conflict |
| `ERR_DUPLICATE_PRO_NUMBER` | 409 Conflict |
| `ERR_DUPLICATE_INVOICE_NUMBER` | 409 Conflict |
| `ERR_DUPLICATE_FX_RATE` | 409 Conflict |
| `ERR_CONTRACT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_GL_ACCOUNT_INACTIVE` | 409 Conflict |
| `ERR_EMPTY_PAYMENT_RUN` | 409 Conflict |
| `ERR_FX_RATE_MISSING` | 409 Conflict |
| `ERR_INVOICE_NOT_PAYABLE` | 409 Conflict |
| `ERR_EXCEPTION_STILL_ACTIVE` | 409 Conflict |
| `ERR_NEGOTIATION_ROUND_LIMIT` | 409 Conflict |
| `ERR_DISPUTE_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_CREDIT_EXCEEDS_DISPUTED` | 409 Conflict |
| `ERR_CLAIM_EXCEEDS_PAID` | 409 Conflict |
| `ERR_RECOVERY_EXCEEDS_CLAIMED` | 409 Conflict |
| `ERR_RUN_DATE_PAST` | 409 Conflict |
| `ERR_CONTRACT_WINDOW_INVALID` | 422 Unprocessable Content |
| `ERR_WEIGHT_BREAK_INVALID` | 422 Unprocessable Content |
| `ERR_AMOUNT_MISMATCH` | 422 Unprocessable Content |
| `ERR_AMOUNT_INVALID` | 422 Unprocessable Content |
| `ERR_ALLOCATION_SUM_INVALID` | 422 Unprocessable Content |
| `ERR_EXPORT_RANGE_INVALID` | 422 Unprocessable Content |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
