# Home-Equity Investment API — Product Requirements Document

## 1. Introduction

A Home-Equity Investment (HEI) lets a homeowner unlock a portion of their property's value today in exchange for the investor sharing in the home's future appreciation — with no monthly payments and no interest accrual in the conventional sense. This document specifies the backend service that runs the full HEI lifecycle: a homeowner applies against a capitalized investor fund, the property is valued by an automated model or an in-person appraisal, an analyst underwrites the request and presents an investment offer, the two sides negotiate through counters and re-presentations, and — once accepted — the deal is funded, secured by a recorded lien, and serviced through periodic maintenance-covenant inspections until the homeowner exits by selling the home or buying the investor out.

The platform coordinates six distinct actors — homeowners, investment analysts, appraisers, closing agents, inspectors, and compliance officers — each with a narrow, auditable slice of authority. The financial heart of the system is the settlement engine: when the homeowner exits, the service computes the investor's share of appreciation (capped by an annualized rate on a sale, uncapped on a buyout), deducts an origination-and-servicing fee, pays off the senior mortgage, and distributes the remainder back to the homeowner as a conserved waterfall in which every cent is accounted for. Because settlements can be disputed and re-proposed, the design layers in optimistic concurrency control, a segregation-of-duties barrier between the officer who proposes a settlement and the officer who resolves a dispute over it, and derived-capital reconciliation that keeps each fund's committed and available balances exact at all times.

This is a strict, contract-first specification. Money is always expressed and stored in integer cents; rounding is deterministic and pinned per component; state transitions and their side effects are exhaustively defined; and a logical clock — never wall-clock time — governs every time-sensitive rule so that the same test replayed twice yields identical results.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming that principal's role. Six roles exist, spelled exactly as follows: `Homeowner`, `InvestmentAnalyst`, `Appraiser`, `ClosingAgent`, `Inspector`, and `ComplianceOfficer`. If either header is missing, or if `X-User-Role` is not one of these six known roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the acting role is not permitted to invoke the requested endpoint per the authorization matrix in Section 4, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Three of the roles are **entity-backed**, meaning `X-User-ID` is the `id` of a persisted record and drives ownership checks:

- When `X-User-Role` is `Homeowner`, `X-User-ID` is the `id` of the acting `Homeowner`; ownership checks on any resource that references a `Homeowner` compare the resource's owning homeowner to `X-User-ID`. Concretely, a homeowner may act only on an `Application` whose `homeowner_id` equals `X-User-ID`, and on the `Offer`, `Agreement`, and `Settlement` records reachable from such an application. A homeowner-owned mutation performed by a different homeowner is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).
- When `X-User-Role` is `Appraiser`, `X-User-ID` is the `id` of the acting `Appraiser`; it identifies which appraiser is completing an appointment.
- When `X-User-Role` is `Inspector`, `X-User-ID` is the `id` of the acting `Inspector`; it identifies which inspector is recording an inspection result.

The other three roles are **opaque operator identifiers** not tied to any persisted entity. When `X-User-Role` is `InvestmentAnalyst`, `ClosingAgent`, or `ComplianceOfficer`, `X-User-ID` is an operator identifier the server does not compare to any entity's `id`. For the `ComplianceOfficer` role the server does record the acting identifier where a scaffold transition writes it — a settlement stores the proposing officer as `proposed_by_user_id`, and a dispute stores the resolving or rejecting officer as `resolved_by_user_id` — but these are captured for the segregation-of-duties rule described in Section 2.8, not used as entity identities.

All six roles may perform every read (`GET`) operation. Write authority is partitioned narrowly and is detailed alongside each workflow in Section 3 and enumerated in the Section 4 endpoint table.

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

All list endpoints accept two optional query parameters, `limit` and `offset`. `limit` defaults to 10, must be at least 1, and may not exceed 100. `offset` defaults to 0 and must be at least 0. Results are always ordered by `created_at` in ascending order (oldest first). Each list response includes, in its `meta` object, the applied `limit` and `offset`, the `total_count` of records matching the filter before pagination, and a `has_more` boolean that is true when records remain beyond the current page.

Every list endpoint additionally supports resource-scoped filters that narrow results by a foreign key or lifecycle `status`, allowing a caller to reach a child record from a parent it already knows. Applications may be filtered by `homeowner_id`, `fund_id`, and `status`; valuations by `application_id`, `source_appointment_id`, `method`, and `status`; appraisal appointments by `appraiser_id`, `valuation_id`, and `status`; offers by `application_id`, `fund_id`, `valuation_id`, and `status`; agreements by `offer_id`, `application_id`, `fund_id`, and `status`; liens by `agreement_id` and `status`; inspections by `agreement_id`, `inspector_id`, and `status`; settlements by `agreement_id` and `status`; and disputes by `settlement_id`, `agreement_id`, and `status`. All filters are optional and combine conjunctively.

### 2.4. Common Resource Properties

Every persisted resource in this system carries a server-minted `id` that is a UUID with no type prefix, a `created_at` timestamp, an `updated_at` timestamp, and an integer `version`. Timestamps are ISO 8601 UTC strings with three fractional (millisecond) digits. `version` begins at 1 when the resource is created and increases by exactly 1 on each mutation that the specification declares to bump it; `updated_at` is refreshed to the current logical-clock instant on every such mutation. The `created_at` value is fixed at creation and never changes. All thirteen resource types — funds, homeowners, applications, valuations, appraisers, appraisal appointments, offers, agreements, liens, inspectors, inspections, settlements, and disputes — expose all four of these common properties.

Path parameters that reference a resource by `id` are validated left to right. For a nested path, each successive `id` segment must resolve to an existing record before the next is considered, and the first unresolved segment yields that resource's specific not-found error, each carrying HTTP 404: an unknown fund yields `ERR_FUND_NOT_FOUND`, a homeowner `ERR_HOMEOWNER_NOT_FOUND`, an application `ERR_APPLICATION_NOT_FOUND`, a valuation `ERR_VALUATION_NOT_FOUND`, an appraiser `ERR_APPRAISER_NOT_FOUND`, an appraisal appointment `ERR_APPOINTMENT_NOT_FOUND`, an offer `ERR_OFFER_NOT_FOUND`, an agreement `ERR_AGREEMENT_NOT_FOUND`, a lien `ERR_LIEN_NOT_FOUND`, an inspector `ERR_INSPECTOR_NOT_FOUND`, an inspection `ERR_INSPECTION_NOT_FOUND`, a settlement `ERR_SETTLEMENT_NOT_FOUND`, and a dispute `ERR_DISPUTE_NOT_FOUND`. The same resource-specific not-found codes are raised when one of these ids is supplied as a body-carried foreign key that fails to resolve.

### 2.5. Monetary Amounts, Precision, and Rounding

All monetary quantities are integer counts of cents; the system never stores fractional cents. Wherever a calculation multiplies a monetary base by a percentage or rate, the result is rounded to whole cents using **round half up** (a value exactly halfway between two cents rounds to the larger cent). Two precision disciplines are load-bearing and must not be simplified:

- **Round per component, then sum.** The settlement fee is assembled from three independently rounded pieces (see Section 3.7). Each percentage-based piece is rounded to whole cents *individually* before the pieces are added together with the flat administrative charge. Summing the raw products first and rounding once at the end is incorrect and will produce off-by-a-cent divergences.
- **Round each side of a cap before comparing.** The investor's appreciation share on a sale is the smaller of a raw share and an annualized cap. Both the raw share and the cap are each rounded to whole cents *before* the smaller of the two is selected (see Section 3.7).

The ratio `combined_ltv` is the sole exception to cent-rounding: it is a pure number retained at full ratio precision and compared exactly, never rounded (see Section 3.3).

### 2.6. Fund Capital Reconciliation

Each `Fund` publishes two derived balances that must remain exact at all times: `committed_capital_cents` and `available_capital_cents`. Committed capital is the sum of `investment_amount_cents` across two populations of that fund: every `Offer` currently in `PRESENTED` status, plus every `Agreement` whose `status` is any of `FUNDED`, `ACTIVE`, `EXIT_INITIATED`, `SETTLEMENT_PROPOSED`, or `DISPUTED`. Offers in `COUNTERED`, `DECLINED`, or `WITHDRAWN` status hold no capital, and agreements in `SETTLED` or `DEFAULTED` status hold none either. Available capital is the fund's `total_capital_cents` minus its `committed_capital_cents`. These two figures are recomputed on every offer or agreement mutation — presentation, counter, re-presentation, decline, withdrawal, acceptance, settlement finalization, and default — and the invariant that committed plus available always equals total capital holds after each. At creation a fund has `committed_capital_cents` equal to 0 and `available_capital_cents` equal to its `total_capital_cents`.

### 2.7. Optimistic Concurrency Control on Settlement Proposals

Proposing a settlement against an agreement is guarded by optimistic concurrency control on the agreement's `version`. A request to propose a settlement on an agreement must carry `expected_agreement_version` holding the client's last observed `version` of that `Agreement`. If that value does not equal the agreement's current `version`, the request is rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412). This barrier matters because a re-proposal legitimately voids and supersedes a prior proposed settlement; a second proposal carrying a stale `expected_agreement_version` is therefore refused rather than being allowed to silently discard a settlement the client never observed. Only the settlement-proposal endpoint takes this version field; no other endpoint requires an expected-version input.

### 2.8. Validation Ordering and Segregation of Duties

When several checks could reject the same request, they are evaluated in a fixed priority order so that the returned error is deterministic. The order is: (1) authentication of the headers, yielding `ERR_UNAUTHENTICATED`; (2) role authorization for the endpoint, yielding `ERR_UNAUTHORIZED`; (3) existence of every resource named in the path, evaluated left to right and yielding that resource's specific not-found error; (4) resource ownership for homeowner-owned actions, yielding `ERR_NOT_RESOURCE_OWNER`; (5) existence of foreign keys carried in the request body (such as `fund_id`, `homeowner_id`, `valuation_id`, `appraiser_id`, and `inspector_id`), yielding the corresponding not-found error; (6) whether the target resource is in a state from which the requested transition is defined, yielding `ERR_INVALID_STATE`; (7) the optimistic-concurrency check on settlement proposals, yielding `ERR_STALE_AGREEMENT_VERSION`; (8) segregation of duties on dispute resolution, yielding `ERR_SEGREGATION_OF_DUTIES`; (9) cross-entity state prerequisites (basis valuation completed, lien recorded, appraiser region match), yielding codes such as `ERR_VALUATION_NOT_COMPLETED`; (10) resource temporal-overlap checks for appraisal and inspection scheduling; (11) constraint gates such as offer expiry, clear title, and time-range validity; and last (12) the fiscal gates such as loan-to-value ceilings, investment caps, fund sufficiency, and non-negative proceeds. Malformed bodies, missing required fields, and bad enum values are surfaced as `ERR_VALIDATION` (HTTP 400) as part of request parsing.

**Segregation of duties.** The officer who resolves or rejects a dispute must not be the officer who proposed the settlement under dispute. Each proposed settlement records the proposing officer's identifier in `proposed_by_user_id`. When a dispute is resolved or rejected, the acting `X-User-ID` is compared against that stored `proposed_by_user_id`; if they are equal the action is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Note that this barrier applies **only** to dispute resolution and rejection: finalizing a settlement carries no such restriction, and the officer who finalizes a settlement is permitted to be the very officer who proposed it.

### 2.9. The Logical Clock

All time-sensitive behavior reads a server-controlled logical clock, never real wall-clock time. Before any clock-setting call the clock reads exactly `2026-07-01T00:00:00Z`. An administrative capability lets an operator advance the clock to a supplied `to_iso8601` instant; this capability is available to the `InvestmentAnalyst`, `ClosingAgent`, and `ComplianceOfficer` roles. The clock's current instant is what stamps `funded_at`, drives offer expiry, and fixes the elapsed-months figure used at settlement.

## 3. Business Logic & Workflows

### 3.1. Funds, Homeowners, and Application Intake

An `InvestmentAnalyst` seeds the platform with the parties and capital it needs. Registering a fund supplies its `name` and its `total_capital_cents`; the fund opens with nothing committed and its entire balance available. Onboarding a homeowner records their `email`, which serves as their login identity, and their `full_name`.

A prospective borrower — acting as a `Homeowner` — opens an application against a specific fund. The submission carries the applicant's own `homeowner_id`, which must equal the acting `X-User-ID`, together with the `fund_id` of the fund being approached, the `property_address`, the `property_type` (one of `SINGLE_FAMILY`, `CONDO`, `TOWNHOUSE`, or `MULTI_UNIT`), the homeowner's own `homeowner_estimated_value_cents`, the `existing_mortgage_balance_cents` still owed on the senior mortgage, and the `requested_investment_cents` the homeowner hopes to draw. A newly created application begins in `DRAFT`. If the referenced `fund_id` does not resolve to a fund the create is rejected with `ERR_FUND_NOT_FOUND`, and if `homeowner_id` does not resolve, with `ERR_HOMEOWNER_NOT_FOUND`.

While an application sits in `DRAFT`, the analyst orders valuations against it (Section 3.2). The homeowner may advance the application from `DRAFT` to `UNDER_REVIEW`, but only once at least one `COMPLETED` valuation exists for that application; submitting with no completed valuation is rejected with `ERR_NO_COMPLETED_VALUATION`. At any point before funding — that is, from `DRAFT`, `UNDER_REVIEW`, `APPROVED`, or `OFFERED` — the owning homeowner may abandon the application, moving it to the terminal `WITHDRAWN` state. Withdrawing from `OFFERED` is permitted only while none of the application's offers has been accepted; when it occurs, every sibling offer still in `PRESENTED` is simultaneously moved to `WITHDRAWN`, which releases the capital those offers were holding back to their fund. The application lifecycle values are `DRAFT`, `UNDER_REVIEW`, `APPROVED`, `OFFERED`, `FUNDED`, `DECLINED`, and `WITHDRAWN`; of these, `FUNDED`, `DECLINED`, and `WITHDRAWN` are terminal.

### 3.2. Property Valuation

Every application must be grounded in an objective property value before it can be underwritten. Two valuation methods exist, and a single application may carry one of each at the same time. A valuation records the `application_id` it belongs to, its `method` (either `AVM` or `APPRAISAL`), the `valued_amount_cents` it establishes, an optional `confidence_score` between 0 and 1 inclusive (which defaults to null and is meaningful only for automated valuations, ignored for appraisals), a `source_appointment_id`, and a `status` drawn from `PENDING`, `COMPLETED`, and `SUPERSEDED`.

An **automated valuation** (`AVM`) is created already complete: the analyst supplies `valued_amount_cents` in the create request and the record is born in `COMPLETED` with `source_appointment_id` null. An **appraisal** (`APPRAISAL`) is created in `PENDING` with no value yet — its `valued_amount_cents` starts at 0 and is filled in only when an in-person appointment is completed. Whenever a valuation becomes `COMPLETED`, any prior `COMPLETED` valuation **of the same method** for the same application is transitioned to `SUPERSEDED`; a new AVM supersedes an older AVM and a new appraisal supersedes an older appraisal, but an AVM and an appraisal never supersede one another and may coexist as two live completed valuations. A `SUPERSEDED` valuation is terminal.

To obtain an appraisal value, the analyst first registers an `Appraiser` with a `full_name` (the appraiser's login identity) and a `region_code` such as CA-BAY, then schedules an appraisal appointment. The appointment references the `appraiser_id`, the `valuation_id` of the pending appraisal it will complete, the `region_code` of the subject property, and a `scheduled_start` and `scheduled_end` given as ISO 8601 UTC instants. Three gates guard scheduling: the referenced valuation must be a `PENDING` appraisal, else `ERR_INVALID_STATE` (HTTP 409); the appointment's `region_code` must equal the appraiser's own `region_code`, else `ERR_APPRAISER_REGION_MISMATCH`; and `scheduled_end` must be strictly after `scheduled_start`, else `ERR_INVALID_TIME_RANGE`. In addition, an appraiser may not be double-booked: if the same appraiser already has a `SCHEDULED` appointment whose window comes within sixty minutes of the requested window — that is, the two windows are separated by strictly less than sixty minutes; windows exactly sixty minutes or more apart do not conflict — the request is rejected with `ERR_APPRAISER_DOUBLE_BOOKED`. An appointment is born `SCHEDULED` and may move to `COMPLETED` or `CANCELLED`.

When the assigned `Appraiser` completes the appointment, they supply the observed `valued_amount_cents`. Completion advances the appointment from `SCHEDULED` to `COMPLETED` and, as a cross-entity effect, drives the linked valuation from `PENDING` to `COMPLETED`, writing the supplied `valued_amount_cents` onto the valuation and stamping the appointment's id as that valuation's `source_appointment_id`; the same-method supersession described above then applies. Completion is only defined when the linked valuation is still `PENDING`; otherwise it is rejected with `ERR_INVALID_STATE`. Alternatively, the analyst may cancel a still-scheduled appointment, moving it to `CANCELLED` and leaving the pending valuation untouched.

### 3.3. Underwriting Decision

Once an application is `UNDER_REVIEW`, an `InvestmentAnalyst` renders a `decision` that is either APPROVE or DECLINE. A decline moves the application straight to the terminal `DECLINED` state with no further computation. An approval moves it from `UNDER_REVIEW` to `APPROVED`, but only after passing a loan-to-value ceiling, and it is at this moment that two derived fields are computed and frozen onto the application.

The underwriting basis is the application's `COMPLETED` valuation with the latest `created_at` — the single most recent completed valuation regardless of method, with `created_at` serving as the unique tie-break. From it the system computes `combined_ltv` as the sum of `requested_investment_cents` and `existing_mortgage_balance_cents`, divided by that basis valuation's `valued_amount_cents`. This ratio is kept at full precision and is never rounded. Approval is allowed only when `combined_ltv` is at most 0.75; if it exceeds 0.75 the approval is rejected with `ERR_LTV_EXCEEDED` and the application stays `UNDER_REVIEW`. When approval succeeds, the computed `combined_ltv` is stored and a `risk_band` is assigned from it: `LOW` when `combined_ltv` is at most 0.50, `MODERATE` when it is greater than 0.50 but at most 0.65, and `ELEVATED` when it is greater than 0.65 (and, necessarily, at most 0.75, since a higher ratio would have been rejected). Both `combined_ltv` and `risk_band` are null on any application that has not yet been approved.

### 3.4. Offer Negotiation

With an application `APPROVED`, the `InvestmentAnalyst` presents an investment offer. Presenting the first offer for an application advances the application from `APPROVED` to `OFFERED`; subsequent offers leave it in `OFFERED`, and multiple concurrent `PRESENTED` offers per application are permitted. An offer records the `application_id` it belongs to (its `fund_id` is copied from that application's fund), the `valuation_id` of the `COMPLETED` valuation used as the pricing basis, the `investment_amount_cents` being offered, the investor's `option_percentage` share of appreciation (a fraction between 0 and 1), a `risk_adjustment_pct` (a downward fraction between 0 and 1), the `term_months` length of the option, a `capped_annual_rate` that will bound the investor's share on a sale, and an `expires_at` instant after which acceptance is refused. A new offer is born `PRESENTED`; its lifecycle values are `PRESENTED`, `ACCEPTED`, `DECLINED`, `COUNTERED`, and `WITHDRAWN`, of which the last four are the possible terminals for `ACCEPTED`, `DECLINED`, and `WITHDRAWN`.

The pricing basis carries two derived guards. First, the offer's `adjusted_start_value_cents` — the value floor from which appreciation is measured — is the basis valuation's `valued_amount_cents` multiplied by one minus `risk_adjustment_pct`, rounded half up to whole cents. Second, the offered `investment_amount_cents` is gated against a loan-to-value cap: the maximum permitted investment is thirty percent of the basis valuation's `valued_amount_cents`, floored to whole cents, and if `investment_amount_cents` exceeds that maximum the presentation is rejected with `ERR_INVESTMENT_EXCEEDS_LTV_CAP`. Because this cap is computed from the *chosen basis*, an amount that is valid against a provisional AVM basis can be rejected against an appraisal basis whose `valued_amount_cents` differs, and vice versa — the same `investment_amount_cents` yields a different ceiling on each basis. Presenting an offer also requires that the chosen basis valuation actually be `COMPLETED`; presenting against a non-completed valuation is rejected with `ERR_VALUATION_NOT_COMPLETED`. Two further guards apply to the money: an offer cannot reserve more than the fund currently holds available — if `investment_amount_cents` exceeds the fund's `available_capital_cents` the presentation is rejected with `ERR_INSUFFICIENT_FUND_CAPITAL` — and presenting an offer reserves that amount by adding it into the fund's committed capital.

The homeowner drives the negotiation from the `PRESENTED` state along one of three paths. **Accepting** moves the offer to `ACCEPTED` and triggers the funding cascade described in Section 3.5; acceptance is refused with `ERR_OFFER_EXPIRED` if the logical clock is at or after the offer's `expires_at`, and it is only defined while the parent application is `OFFERED`. **Declining** moves the offer to the terminal `DECLINED` state and releases its reserved amount from the fund's committed capital, raising available capital by the same amount. **Countering** moves the offer to `COUNTERED`, records the homeowner's `counter_notes` rationale, and likewise releases the reserved amount — a `COUNTERED` offer holds no capital. From `COUNTERED`, the analyst may **re-present** revised terms, moving the offer back to `PRESENTED` in a loop; the re-presentation may overwrite any of `investment_amount_cents`, `option_percentage`, `risk_adjustment_pct`, `term_months`, `capped_annual_rate`, and `expires_at`, recomputes `adjusted_start_value_cents` from the revised risk adjustment, and re-reserves the (possibly new) `investment_amount_cents` back into the fund's committed capital. A re-presentation whose revised `investment_amount_cents` would exceed the fund's `available_capital_cents` is rejected with `ERR_INSUFFICIENT_FUND_CAPITAL`. Separately, the analyst may **withdraw** a still-presented offer to the terminal `WITHDRAWN` state, which also releases its reserved amount from committed capital. Every one of these transitions recomputes the fund's committed and available balances so that capital is conserved.

### 3.5. Funding, Lien, and Activation

Acceptance of an offer sets off a cascade that funds the deal. In one atomic step the accepted offer moves to `ACCEPTED`; the parent application moves from `OFFERED` to `FUNDED`; and every sibling offer of that application still in `PRESENTED` is moved to `DECLINED`, releasing the capital each was holding. The system then mints a new `Agreement` copying the accepted offer's terms — the `offer_id`, `application_id`, and `fund_id`, together with `investment_amount_cents`, `option_percentage`, `adjusted_start_value_cents`, `term_months`, and `capped_annual_rate` — and stamps `funded_at` with the current logical-clock instant and `maturity_at` with that instant plus `term_months` calendar months. A funded agreement is born in `status` `FUNDED` with `covenant_status` `COMPLIANT`; its lifecycle states are `FUNDED`, `ACTIVE`, `EXIT_INITIATED`, `SETTLEMENT_PROPOSED`, `DISPUTED`, `SETTLED`, and `DEFAULTED`, the last two terminal. Alongside the agreement, the system creates a `Lien` in `PENDING` status with `title_status` `PENDING` and a null `lien_position`, referencing the new `agreement_id`. Finally the fund's committed and available capital are recomputed to reflect the accepted offer becoming a funded agreement and the losing siblings releasing their holds.

A funded agreement is not yet live. A `ClosingAgent` records the lien by supplying the resolved `title_status` — either `CLEAR` or `CLOUDED` — and the numeric `lien_position` (for instance, 2 for a second lien). Recording moves the lien from `PENDING` to `RECORDED`, but only if the title resolves to `CLEAR`; a `CLOUDED` title is rejected with `ERR_TITLE_NOT_CLEAR` and the lien stays `PENDING`. Once the lien is `RECORDED`, the closing agent activates the agreement, moving it from `FUNDED` to `ACTIVE`. Activation is refused with `ERR_LIEN_NOT_RECORDED` while the agreement's lien has not yet reached `RECORDED`. A lien's terminal state, `RELEASED`, is reached only by system action when the agreement's settlement is finalized (Section 3.7).

Once an agreement is `ACTIVE`, the owning homeowner may initiate an exit, moving it from `ACTIVE` to `EXIT_INITIATED`. This is blocked while a maintenance-covenant breach is open — if the agreement's `covenant_status` is `BREACH_NOTICED`, the request is rejected with `ERR_COVENANT_BREACH_OPEN` (see Section 3.6). Separately, a `ComplianceOfficer` may declare a default on an active agreement, moving it from `ACTIVE` to the terminal `DEFAULTED` state; a default is only permitted when a covenant breach is actually open, that is, when `covenant_status` is `BREACH_NOTICED`, else it is rejected with `ERR_NO_OPEN_BREACH`. A defaulted agreement releases its committed capital back to the fund.

### 3.6. Servicing and the Maintenance Covenant

Throughout an agreement's life the property is expected to be kept in good condition, and this is monitored through inspections. An `InvestmentAnalyst` or a `ClosingAgent` schedules an inspection against an agreement, supplying the `inspector_id` and a `scheduled_date` expressed as a calendar date in `YYYY-MM-DD` form with no time of day. An `Inspector` is registered beforehand with a `full_name` (their login identity) and a `region_code`. Because an inspector handles at most one property per day, scheduling is rejected with `ERR_INSPECTOR_DOUBLE_BOOKED` if that inspector already holds a non-cancelled inspection on the same `scheduled_date`. An inspection is born `SCHEDULED`, with a null `condition_score`, and its lifecycle values are `SCHEDULED`, `PASSED`, `FAILED`, and `CANCELLED`.

When the assigned inspector records a result, they supply a `result` of either PASSED or FAILED together with a `condition_score` between 0 and 100. A pass moves the inspection from `SCHEDULED` to `PASSED`; a fail moves it to `FAILED`; either way the supplied `condition_score` is written onto the inspection. The maintenance covenant is tracked on the agreement as a `covenant_status` dimension that runs independently of the agreement's main `status`, taking the values `COMPLIANT`, `BREACH_NOTICED`, and `CURED`. A failed inspection is a covenant event: if the agreement's `covenant_status` is `COMPLIANT` or `CURED`, it moves to `BREACH_NOTICED`. A subsequent passing inspection is a cure: if the agreement is currently in `BREACH_NOTICED`, a pass moves `covenant_status` to `CURED`. A later failure after a cure returns it to `BREACH_NOTICED`, so the covenant can cycle between breach and cure over the life of the deal. An open breach — `covenant_status` equal to `BREACH_NOTICED` — is what blocks the homeowner's exit initiation and what enables a compliance default, as described in Section 3.5. An `InvestmentAnalyst` may also cancel a still-scheduled inspection, moving it to `CANCELLED`; scheduled inspections are additionally cancelled in bulk by the system when a settlement is finalized.

### 3.7. Exit and Settlement

Settlement is where the investment is unwound and the money is divided. Only a `ComplianceOfficer` proposes a settlement, and only against an agreement that has left the active phase. The first proposal moves the agreement from `EXIT_INITIATED` to `SETTLEMENT_PROPOSED`; a re-proposal against an agreement already in `SETTLEMENT_PROPOSED` keeps it in that state while replacing the prior settlement. Each proposal carries the exit `settlement_type` — either `SALE` or `BUYOUT` — the senior `mortgage_payoff_cents` to be cleared at closing, and the `expected_agreement_version` for the optimistic-concurrency check of Section 2.7. A `SALE` must carry `sale_price_cents` (and ignores any appraised value); a `BUYOUT` must carry `current_appraised_value_cents` (and ignores any sale price). A proposal missing the value required by its type is rejected with `ERR_VALIDATION`. Every proposal creates a `Settlement` in `PROPOSED` status, records the proposing officer in `proposed_by_user_id`, and increments the agreement's `version` by 1. On a re-proposal, the prior `PROPOSED` settlement is first moved to `VOID`; a settlement's lifecycle values are `PROPOSED`, `DISPUTED`, `FINALIZED`, and `VOID`.

At proposal time the settlement's derived figures are computed and stored. The **ending value** (`ending_value_cents`) is the `sale_price_cents` for a sale and the `current_appraised_value_cents` for a buyout. The **elapsed term** (`elapsed_months`) is the whole number of calendar months from the agreement's `funded_at` to the current logical-clock instant.

The **investor's appreciation share** (`appreciation_share_cents`) is built in two rounded pieces. The raw share is the agreement's `option_percentage` multiplied by the property's gain — the greater of zero and the ending value minus the agreement's `adjusted_start_value_cents` — rounded half up to whole cents. The annualized cap is the agreement's `investment_amount_cents` multiplied by its `capped_annual_rate`, multiplied by `elapsed_months`, divided by twelve months in a year, rounded half up to whole cents. Each of these two amounts is rounded to whole cents before they are compared. For a `SALE`, the appreciation share is the **smaller** of the raw share and the cap — the annual cap can bind and lower the share. For a `BUYOUT`, the appreciation share is the raw share with **no cap** applied; consequently, for an identical ending value, a buyout share can exceed the corresponding sale share whenever the cap would have bound.

The **settlement fee** (`settlement_fee_cents`) is assembled by rounding each component individually and then summing: an origination component of three percent of the agreement's `investment_amount_cents` rounded half up to whole cents, plus a servicing component of one percent of the settlement's `ending_value_cents` rounded half up to whole cents, plus a flat administrative charge of fifty thousand cents. The three rounded pieces are then added; the sum is never re-rounded.

The proceeds then flow through a conserved waterfall. **Net proceeds** (`net_proceeds_cents`) are the ending value minus the `mortgage_payoff_cents` minus the `settlement_fee_cents`. The **homeowner payout** (`homeowner_payout_cents`) is the net proceeds minus the agreement's `investment_amount_cents` minus the `appreciation_share_cents`. The homeowner payout is the balancing remainder: the mortgage payoff, the settlement fee, the investor's returned principal, the investor's appreciation share, and the homeowner payout together always sum back to the ending value.

A `ComplianceOfficer` finalizes a proposed settlement, moving it from `PROPOSED` to `FINALIZED`. Finalization is only defined while the settlement is `PROPOSED` and its parent agreement is `SETTLEMENT_PROPOSED`, and it is refused with `ERR_PROCEEDS_INSUFFICIENT` if `net_proceeds_cents` is negative. As noted in Section 2.8, the finalizing officer is allowed to be the same officer who proposed the settlement. Finalization drives a depth-three cascade: the settlement becomes `FINALIZED`; the agreement moves from `SETTLEMENT_PROPOSED` to the terminal `SETTLED`; the agreement's lien moves from `RECORDED` to `RELEASED`; and every inspection of that agreement still in `SCHEDULED` is moved to `CANCELLED`. A settled agreement releases its committed capital back to the fund.

### 3.8. Disputes and Segregation of Duties

A homeowner who disagrees with a proposed settlement may dispute it. Disputing moves the settlement from `PROPOSED` to `DISPUTED` and the parent agreement from `SETTLEMENT_PROPOSED` to `DISPUTED`, and it opens a `Dispute` record. The dispute captures the `settlement_id` under contest (from which its `agreement_id` is copied), the homeowner's `reason`, and their claimed `disputed_value_cents`; it also carries a `resolved_value_cents` and a `resolved_by_user_id` that stay null until the dispute is closed. A dispute's lifecycle values are `OPEN`, `RESOLVED`, and `REJECTED`.

A `ComplianceOfficer` closes an open dispute one of two ways, and both are subject to the segregation-of-duties barrier of Section 2.8: the acting `X-User-ID` must differ from the disputed settlement's `proposed_by_user_id`, else the action is rejected with `ERR_SEGREGATION_OF_DUTIES`. **Resolving** the dispute records an adjusted `resolved_value_cents` and the acting officer in `resolved_by_user_id`, voids the disputed settlement, and moves the agreement from `DISPUTED` back to `SETTLEMENT_PROPOSED` by creating a fresh replacement settlement whose ending value is taken from that `resolved_value_cents` (the replacement inherits the voided settlement's `settlement_type` and `mortgage_payoff_cents`, records the resolving officer as its `proposed_by_user_id`, and has all derived figures recomputed accordingly); this increments the agreement's `version` by 1. **Rejecting** the dispute instead records the acting officer in `resolved_by_user_id`, reinstates the original settlement by moving it from `DISPUTED` back to `PROPOSED`, and moves the agreement from `DISPUTED` back to `SETTLEMENT_PROPOSED`, leaving the original figures intact; the agreement's `version` is not incremented on a rejection.

## 4. Endpoint Definitions

The table below lists every endpoint with its authorized roles. Successful creation of a new resource returns HTTP 201; successful reads and state-changing actions on existing resources return HTTP 200. Request bodies, response payloads, and side effects are not repeated here — they are specified in the Section 3 workflows. "All roles" denotes `Homeowner`, `InvestmentAnalyst`, `Appraiser`, `ClosingAgent`, `Inspector`, and `ComplianceOfficer`.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Advance the server logical clock | `InvestmentAnalyst`, `ClosingAgent`, `ComplianceOfficer` |
| POST | `/hei/funds` | Create an investor fund | `InvestmentAnalyst` |
| GET | `/hei/funds/{id}` | Get a fund | All roles |
| POST | `/hei/homeowners` | Onboard a homeowner | `InvestmentAnalyst` |
| GET | `/hei/homeowners/{id}` | Get a homeowner | All roles |
| POST | `/hei/applications` | Submit a draft application | `Homeowner` |
| GET | `/hei/applications/{id}` | Get an application | All roles |
| GET | `/hei/applications` | List/filter applications | All roles |
| POST | `/hei/applications/{id}/submit` | Submit for review | `Homeowner` |
| POST | `/hei/applications/{id}/decision` | Approve or decline an application | `InvestmentAnalyst` |
| POST | `/hei/applications/{id}/withdraw` | Withdraw an application | `Homeowner` |
| POST | `/hei/applications/{id}/valuations` | Create a valuation for an application | `InvestmentAnalyst` |
| GET | `/hei/valuations/{id}` | Get a valuation | All roles |
| GET | `/hei/valuations` | List/filter valuations | All roles |
| POST | `/hei/appraisers` | Register an appraiser | `InvestmentAnalyst` |
| GET | `/hei/appraisers/{id}` | Get an appraiser | All roles |
| POST | `/hei/appraisal-appointments` | Schedule an appraisal appointment | `InvestmentAnalyst` |
| GET | `/hei/appraisal-appointments/{id}` | Get an appointment | All roles |
| GET | `/hei/appraisal-appointments` | List/filter appointments | All roles |
| POST | `/hei/appraisal-appointments/{id}/complete` | Complete an appointment and record value | `Appraiser` |
| POST | `/hei/appraisal-appointments/{id}/cancel` | Cancel a scheduled appointment | `InvestmentAnalyst` |
| POST | `/hei/applications/{id}/offers` | Present an offer | `InvestmentAnalyst` |
| GET | `/hei/offers/{id}` | Get an offer | All roles |
| GET | `/hei/offers` | List/filter offers | All roles |
| POST | `/hei/offers/{id}/accept` | Accept an offer | `Homeowner` |
| POST | `/hei/offers/{id}/decline` | Decline an offer | `Homeowner` |
| POST | `/hei/offers/{id}/counter` | Counter an offer | `Homeowner` |
| POST | `/hei/offers/{id}/represent` | Re-present revised offer terms | `InvestmentAnalyst` |
| POST | `/hei/offers/{id}/withdraw` | Withdraw an offer | `InvestmentAnalyst` |
| GET | `/hei/agreements/{id}` | Get an agreement | All roles |
| GET | `/hei/agreements` | List/filter agreements | All roles |
| POST | `/hei/agreements/{id}/activate` | Activate a funded agreement | `ClosingAgent` |
| POST | `/hei/agreements/{id}/initiate-exit` | Initiate exit | `Homeowner` |
| POST | `/hei/agreements/{id}/default` | Declare a default | `ComplianceOfficer` |
| GET | `/hei/liens/{id}` | Get a lien | All roles |
| GET | `/hei/liens` | List/filter liens | All roles |
| POST | `/hei/liens/{id}/record` | Record the lien and title result | `ClosingAgent` |
| POST | `/hei/inspectors` | Register an inspector | `InvestmentAnalyst` |
| GET | `/hei/inspectors/{id}` | Get an inspector | All roles |
| POST | `/hei/agreements/{id}/inspections` | Schedule a maintenance inspection | `InvestmentAnalyst`, `ClosingAgent` |
| GET | `/hei/inspections/{id}` | Get an inspection | All roles |
| GET | `/hei/inspections` | List/filter inspections | All roles |
| POST | `/hei/inspections/{id}/complete` | Record an inspection result | `Inspector` |
| POST | `/hei/inspections/{id}/cancel` | Cancel a scheduled inspection | `InvestmentAnalyst` |
| POST | `/hei/agreements/{id}/settlements` | Propose a settlement | `ComplianceOfficer` |
| GET | `/hei/settlements/{id}` | Get a settlement | All roles |
| GET | `/hei/settlements` | List/filter settlements | All roles |
| POST | `/hei/settlements/{id}/finalize` | Finalize a settlement | `ComplianceOfficer` |
| POST | `/hei/settlements/{id}/dispute` | Dispute a proposed settlement | `Homeowner` |
| GET | `/hei/disputes/{id}` | Get a dispute | All roles |
| GET | `/hei/disputes` | List/filter disputes | All roles |
| POST | `/hei/disputes/{id}/resolve` | Resolve a dispute | `ComplianceOfficer` |
| POST | `/hei/disputes/{id}/reject` | Reject a dispute | `ComplianceOfficer` |

## 5. Error Code Catalogue

The trigger condition for each error is specified in the Section 2 and Section 3 narratives.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_TIME_RANGE` | 400 |
| `ERR_FUND_NOT_FOUND` | 404 |
| `ERR_HOMEOWNER_NOT_FOUND` | 404 |
| `ERR_APPLICATION_NOT_FOUND` | 404 |
| `ERR_VALUATION_NOT_FOUND` | 404 |
| `ERR_APPRAISER_NOT_FOUND` | 404 |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 |
| `ERR_OFFER_NOT_FOUND` | 404 |
| `ERR_AGREEMENT_NOT_FOUND` | 404 |
| `ERR_LIEN_NOT_FOUND` | 404 |
| `ERR_INSPECTOR_NOT_FOUND` | 404 |
| `ERR_INSPECTION_NOT_FOUND` | 404 |
| `ERR_SETTLEMENT_NOT_FOUND` | 404 |
| `ERR_DISPUTE_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_AGREEMENT_VERSION` | 412 |
| `ERR_NO_COMPLETED_VALUATION` | 409 |
| `ERR_VALUATION_NOT_COMPLETED` | 409 |
| `ERR_LIEN_NOT_RECORDED` | 409 |
| `ERR_TITLE_NOT_CLEAR` | 409 |
| `ERR_APPRAISER_REGION_MISMATCH` | 409 |
| `ERR_APPRAISER_DOUBLE_BOOKED` | 409 |
| `ERR_INSPECTOR_DOUBLE_BOOKED` | 409 |
| `ERR_OFFER_EXPIRED` | 409 |
| `ERR_COVENANT_BREACH_OPEN` | 409 |
| `ERR_NO_OPEN_BREACH` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_LTV_EXCEEDED` | 422 |
| `ERR_INVESTMENT_EXCEEDS_LTV_CAP` | 422 |
| `ERR_INSUFFICIENT_FUND_CAPITAL` | 422 |
| `ERR_PROCEEDS_INSUFFICIENT` | 422 |




