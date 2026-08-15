# Net Lease Acquisition API — Product Requirements Document

## 1. Introduction

Acquiring a net-lease asset for a REIT portfolio is a long, multi-party process in which underwriting discipline, third-party diligence, and financing commitments must line up before escrow can close. Deals routinely die because an estoppel never came back, a title exception surfaced too late, or a financing contingency quietly lapsed while an analyst was waiting on a committee signature. The Net Lease Acquisition API is the system of record for that pipeline: it tracks every acquisition deal from sourcing through due diligence, financing, closing, and the post-closing true-up, and it enforces the segregation-of-duties and timing rules that acquisitions committees and auditors expect.

The API is organized around a **Deal** aggregate. Properties, leases, underwriting models, the purchase agreement, diligence milestones, title reviews with their exceptions, environmental and property-condition assessments, estoppel certificates, SNDAs, financing applications, and closing statements with proration lines and true-up adjustments all hang off a deal (or off one of its children). A derived **deal posture** aggregates the state of these artifacts into a single gate value, so that the question "can this deal close?" is answerable at any moment without walking the tree by hand.

Because diligence deadlines are contractual, the system runs on a **logical clock** rather than wall-clock time. The clock is readable by every rule in this document — milestone overdue detection, estoppel expiry, financing contingency lapse, and remaining-lease-term computation all read the same logical instant — and it is advanced only through an administrative capability intended for test-driving and operational control. All API routes are mounted under `/acquisition-deals` (with tenants and the clock as the only top-level exceptions).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request missing either header, or presenting a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not authorized for the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The system recognizes seven roles, spelled exactly as follows: `AcquisitionsAnalyst`, `UnderwritingCommittee`, `DueDiligenceOfficer`, `CapitalMarketsOfficer`, `EscrowOfficer`, `AssetManager`, and `PlatformAdmin`. For every one of these roles, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it where a workflow needs an actor trail — for example, to decide segregation-of-duties comparisons between a submitter and an approver — but it is never compared against the `id` of any stored resource, and no resource in the system is "owned" by a user in the foreign-key sense. Segregation-of-duties checks compare the `X-User-ID` values carried on two different requests (the proposing request and the approving request), never a header against an entity field.

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

List endpoints accept two query parameters. `limit` caps the number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` skips that many items from the front of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` envelope of a list response carries `limit`, `offset`, `total_count`, and `has_more` so a client can page deterministically through a collection.

### 2.4. Common Resource Properties

Every entity in the system carries a server-minted `id` formatted as a bare UUID with no type prefix, plus a `created_at` timestamp in ISO 8601 UTC with three fractional digits. All entities except proration lines additionally carry `updated_at` (ISO 8601 UTC, three fractional digits, refreshed on every mutation) and `version` (an integer starting at its initial value and incremented by one on every mutation). Proration lines are immutable once created — corrections happen exclusively through true-up adjustments on the owning statement — so a `Proration` carries only `id` and `created_at`; both `updated_at` and `version` are absent from that resource. Any side effect that mutates a resource (for example, a cascade that flips a deal's posture or bumps a purchase agreement's amendment count) refreshes that resource's `updated_at` and increments its `version` as part of the same atomic request.

### 2.5. Monetary Representation, Precision, and Rounding

All money in the system is integer cents: prices, rents, deposits, fees, reserves, proration amounts, and adjustment amounts are stored and returned as whole-cent integers, never floats. Where a calculation produces a fractional result — basis-point ratios, per-line prorations, amortizing loan payments, the weighted average lease term, the DSCR — the rule is **round half up** to the declared precision of that field. Basis-point fields (`cap_rate_bps`, `cash_on_cash_bps`) are integer basis points; `dscr` is a number carried to 4 decimal places; `walt_months` and `remaining_term_months` are integer months. Where a formula is composed of multiple steps, the scaffold-pinned evaluation order governs: per-line prorations are rounded first and then summed into the statement total, and the amortizing loan payment is rounded to cents first and only then multiplied by twelve to obtain the annual figure. Reordering those steps is forbidden because it produces different cents.

### 2.6. The Logical Clock and Time-Driven Transitions

The system maintains a single logical clock that every date comparison in this document reads. At server startup the clock reads exactly `2026-08-01T00:00:00Z`; until it is explicitly set, the clock must not fall back to wall-clock time. A `PlatformAdmin` may advance the logical clock to a supplied `to_iso8601` instant through the administrative clock capability. Advancing the clock fires any time-based system transitions whose trigger instant has been crossed: a pending diligence milestone whose `due_date` has passed flips to `OVERDUE` and pushes the deal posture to `DD_BLOCKED`; a requested-but-never-received estoppel certificate goes `EXPIRED` once the logical clock passes the deal's `dd_period_end`, dragging its collection milestone to `OVERDUE`; and a financing application still sitting in `SUBMITTED` when the clock passes the deal's `financing_contingency_end` lapses to `LAPSED`, which marks the financing milestone `OVERDUE` and recomputes the deal posture. All such cascades are atomic within the clock-set request.

### 2.7. Deal Posture as a Derived Aggregate Gate

Alongside its lifecycle `status`, every deal carries a computed `posture` — one of `SOURCING`, `UNDER_REVIEW`, `DD_OPEN`, `DD_BLOCKED`, `CLEAR_TO_CLOSE`, `CLOSED`, or `TERMINATED` — that aggregates the state of the deal's milestones, title exceptions, environmental assessments, estoppels, SNDAs, and financing into a single gate. Posture is never set directly by a client; it is recomputed whenever a contributing artifact changes state. Blocking events (a `FATAL` title exception raised, an environmental assessment failed, a milestone rolling `OVERDUE`, a financing application lapsing) push the posture to `DD_BLOCKED`; clearing the blocking condition recomputes the posture, which may return the deal to `DD_OPEN`. Certification by the `UnderwritingCommittee` is the only path into `CLEAR_TO_CLOSE`, and closing or terminating the deal lands the posture in the matching terminal value.

### 2.8. Nested Resource Retrieval and Validation Order

Endpoints addressing nested resources validate path identifiers left to right. A request naming a deal, then a property, then a lease first checks the deal's existence (else `ERR_DEAL_NOT_FOUND`), then the property within that deal (else `ERR_PROPERTY_NOT_FOUND`), then the lease within that property (else `ERR_LEASE_NOT_FOUND`), and so on down the hierarchy — title review then exception, statement then proration or true-up adjustment. Each missing identifier produces its own entity-specific 404, and the first missing identifier wins. The full set of not-found codes is: `ERR_DEAL_NOT_FOUND`, `ERR_TENANT_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_LEASE_NOT_FOUND`, `ERR_MODEL_NOT_FOUND`, `ERR_PSA_NOT_FOUND`, `ERR_MILESTONE_NOT_FOUND`, `ERR_TITLE_REVIEW_NOT_FOUND`, `ERR_EXCEPTION_NOT_FOUND`, `ERR_EA_NOT_FOUND`, `ERR_PCA_NOT_FOUND`, `ERR_ESTOPPEL_NOT_FOUND`, `ERR_SNDA_NOT_FOUND`, `ERR_FINANCING_NOT_FOUND`, `ERR_STATEMENT_NOT_FOUND`, `ERR_PRORATION_NOT_FOUND`, and `ERR_TRUE_UP_NOT_FOUND` — each names the entity whose identifier failed lookup. Beyond path parameters, validation across all endpoints proceeds in a fixed priority order: authentication-header checks first (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), then role authorization (`ERR_INSUFFICIENT_PERMISSIONS`), then path existence, then body foreign-key existence (`ERR_REFERENCED_RESOURCE_NOT_FOUND`, 422), then from-state validity for the requested transition (the entity-specific 409 state errors), then optimistic-concurrency version checks (412), then segregation-of-duties (403), then business-safety rules, and finally the business constraint, fiscal, temporal, and referential gate rules described in §3. This ordering matters: a stale-version rejection surfaces before a segregation-of-duties violation, and an authorization failure surfaces before any 404.

### 2.9. Optimistic Concurrency Control

Two write operations in the system are guarded by optimistic concurrency control, and only those two. Reissuing a closing statement requires the request body to carry `expected_deal_version` holding the `version` of the parent deal as the client last observed it; if the deal's current `version` has advanced beyond that value — because another writer changed deal-level state such as posture or price since the client computed the reissue basis — the reissue is rejected with `ERR_STALE_DEAL_VERSION` (HTTP 412). Amending a purchase agreement likewise requires `expected_psa_version` matching the purchase agreement's current `version`; a mismatch is rejected with `ERR_STALE_PSA_VERSION` (HTTP 412), so a writer never amends terms on a stale view of the price. No other endpoint accepts a version field: clients do not send expected versions on creates, state transitions, or reads outside these two operations.

### 2.10. Segregation of Duties

Three approval actions are segregation-of-duties controlled, each in the same shape: the identity acting on the approval must differ from the identity that performed the earlier originating step, and a match is rejected with `ERR_SOD_VIOLATION` (HTTP 403). Approving or rejecting an underwriting model requires the `UnderwritingCommittee` actor's `X-User-ID` to differ from the analyst identity that submitted the model. Acknowledging a closing statement requires the acknowledging `AcquisitionsAnalyst` identity to differ from the `EscrowOfficer` identity that issued the statement. Asset-manager approval of a true-up adjustment requires the `AssetManager` identity to differ from the identity that proposed the adjustment. The comparisons are between opaque header identities recorded at each step, per §2.1.

### 2.11. Version Pinning of the Underwriting Model

Executing a purchase agreement pins the deal to the underwriting model that was most recently approved at that instant: the deal's `pinned_underwriting_model_id` captures that model's `id`. Approving a newer model afterwards supersedes the previously approved one, but the pin does not move once the deal has reached `PSA_EXECUTED` — the deal stays pinned to the model the committee saw when it executed. Certification of clear-to-close then checks that the pinned model is still the latest approved model; if a newer approval has superseded it, certification fails with `ERR_STALE_UNDERWRITING_MODEL` until the pin is refreshed. Before execution, approving a model refreshes the deal's pin freely.

## 3. Business Logic & Workflows

### 3.1. Sourcing a Deal and Registering Tenants

An `AcquisitionsAnalyst` opens a new deal by supplying a `deal_name`, a `deal_type` of `SINGLE_TENANT`, `MULTI_TENANT`, `SALE_LEASEBACK`, or `PORTFOLIO`, the `target_close_date`, the `earnest_money_cents` deposit, and the `purchase_price_cents` contract price. The `sourcing_channel` — one of `BROKER`, `OFF_MARKET`, `AUCTION`, or `DIRECT` — defaults to `BROKER` when omitted. The target close date must fall at least 30 days after the deal's creation date; anything closer is rejected with `ERR_FIELD_CONSTRAINT_VIOLATION` (HTTP 400). A new deal is born with `status` `SOURCING`, `posture` `SOURCING`, and `earnest_money_released` false.

Tenants are registered independently of any deal. An analyst creates a tenant with its `legal_name`, a `credit_rating` of `INVESTMENT_GRADE`, `NON_INVESTMENT_GRADE`, or `UNRATED`, a numeric `credit_score` between 0 and 1000, `annual_revenue_cents`, and optionally `is_guaranteed` (defaulting to false) to record whether a parent guarantee stands behind the lease. A tenant's `credit_assessment_status` begins at `PENDING`. The `UnderwritingCommittee` moves it to `ANALYZED` by analyzing the credit, and from `ANALYZED` the committee either approves or rejects it. Approval carries one tenant-quality gate: a tenant whose `credit_rating` is `UNRATED` and for whom `is_guaranteed` is false cannot be credit-approved — the attempt is rejected with `ERR_UNRATED_UNGUARANTEED_TENANT` (HTTP 422). Attempting any of these credit transitions from the wrong state yields `ERR_TENANT_CREDIT_INVALID_STATE` (HTTP 409). Only a tenant whose credit is `APPROVED` can stand behind a verified lease, as described below.

### 3.2. Properties, Leases, and Rollover Risk

Properties join a deal when an analyst supplies an `address`, a `property_type` of `RETAIL`, `INDUSTRIAL`, `OFFICE`, `MEDICAL`, or `QSR`, the `rentable_sqft`, and the `year_built`. Square footage must be greater than zero, and the year built must be at least 1800 and no later than the current logical year; violations return `ERR_FIELD_CONSTRAINT_VIOLATION`. A property starts `IDENTIFIED`; a `DueDiligenceOfficer` later marks it `SURVEYED` and then either `CLEAR` or `FLAGGED`, with a wrong-from-state attempt rejected as `ERR_PROPERTY_INVALID_STATE`.

Leases are drafted against a property — the lease's `property_id` points back to the property it sits on — with a payload naming the `tenant_id`, the `lease_type` (`NNN`, `NN`, `GROSS`, or `ABSOLUTE_NET`), the `annual_base_rent_cents`, the `lease_commencement_date`, and the `lease_expiration_date`, plus an optional `renewal_options_count` defaulting to zero. The expiration must be strictly later than the commencement, again under `ERR_FIELD_CONSTRAINT_VIOLATION`, and the referenced tenant must exist or the create fails with `ERR_REFERENCED_RESOURCE_NOT_FOUND`. A lease starts in `DRAFT`. Verification by an analyst requires the tenant's credit assessment to be `APPROVED` — otherwise `ERR_TENANT_CREDIT_NOT_APPROVED` (HTTP 422) — and a lease not in `DRAFT` cannot be verified (`ERR_LEASE_INVALID_STATE`). Verification computes two derived fields. The `remaining_term_months` is the whole-month count between the logical clock's current instant and the `lease_expiration_date`: take the expiry year minus the current year, multiply by twelve, add the expiry month minus the current month, subtract one if the expiry day-of-month is earlier than the current day-of-month (a partial month in progress is not counted), and floor the result at zero. The `rollover_risk_tier` is then assigned by strict thresholds on that figure: fewer than 24 months remaining is `CRITICAL`; at least 24 but fewer than 60 is `HIGH`; at least 60 but fewer than 120 is `MEDIUM`; 120 or more is `LOW`. The boundaries are inclusive of the upper tier — exactly 24 months is `HIGH`, not `CRITICAL`; exactly 60 is `MEDIUM`; exactly 120 is `LOW`.

Once verified, a lease participates in the estoppel loop described in §3.6: receipt of a tenant's estoppel certificate moves the lease from `VERIFIED` to `ESTOPPEL_PENDING`, certification moves it to `ESTOPPELED`, a deficient certificate returns it to `VERIFIED` so a fresh certificate can be requested, and a later re-confirmation round — a new certificate received after a prior certification — moves an `ESTOPPELED` lease back to `ESTOPPEL_PENDING` until the new certificate is itself certified.

### 3.3. Underwriting: NOI, Cap Rate, Cash-on-Cash, and WALT

Underwriting models are created per deal by an analyst. Each model is assigned a `model_version` monotonically per deal — one greater than the maximum existing version — starts in `DRAFT`, and computes its figures at creation and again on submission and approval. The analyst may choose the `opex_allowance_variant`: `CONSERVATIVE` (the default) or `MARKET`.

Net operating income aggregates the deal's rent roll. Collect every lease across all of the deal's properties whose status is `VERIFIED`, `ESTOPPEL_PENDING`, or `ESTOPPELED` — `DRAFT` and `EXPIRED` leases are excluded — and sum their `annual_base_rent_cents` into a gross rent figure. The operating-expense allowance is that gross rent multiplied by the variant's percentage: fifteen percent under `CONSERVATIVE`, twelve percent under `MARKET`. The `noi_cents` is the gross rent minus the allowance. The arithmetic is integer multiplication followed by truncation to whole cents; no rounding mode applies. The two variants therefore produce different NOI from identical lease data — the market variant's smaller allowance yields the higher NOI.

The `cap_rate_bps` is the model's NOI multiplied by ten thousand and divided by the deal's `purchase_price_cents`, rounded half up to integer basis points. Submission is only accepted when the cap rate lands in the band from 300 to 1200 basis points inclusive; outside the band the submission is rejected with `ERR_CAP_RATE_OUT_OF_BAND` (HTTP 422). Submission also requires a strictly positive NOI, failing which it is rejected with `ERR_NOI_NON_POSITIVE` (HTTP 422). A model not in `DRAFT` cannot be submitted (`ERR_MODEL_INVALID_STATE`, HTTP 409).

When a financing application exists on the deal, the model additionally computes a `cash_on_cash_bps` — the dual-variant counterpart to the cap rate. Equity is the `purchase_price_cents` minus the financing application's `loan_amount_cents` plus its `assumption_fee_cents`. The cash-on-cash return is the NOI minus the application's `annual_debt_service_cents`, the difference multiplied by ten thousand and divided by that equity figure, rounded half up to integer basis points. Same NOI input as the cap rate, different denominator and a debt-service subtraction: the two returns deliberately diverge for identical deal data.

The `walt_months` is the weighted average lease term across the same included lease set (statuses `VERIFIED`, `ESTOPPEL_PENDING`, `ESTOPPELED`): each lease contributes its `annual_base_rent_cents` as the weight and its `remaining_term_months` as the term; the WALT is the sum over leases of weight-times-term divided by the sum of weights, rounded half up to integer months. If no leases qualify, `walt_months` is zero.

Committee review follows submission. Approving or rejecting requires the model to be `SUBMITTED` (else `ERR_MODEL_INVALID_STATE`), and the segregation-of-duties rule of §2.10 applies to both decisions. Approval flips every other `APPROVED` model on the deal to `SUPERSEDED`; if the deal has not yet executed its PSA, the deal's `pinned_underwriting_model_id` is refreshed to the newly approved model, but after execution the pin is frozen per §2.11, and superseding the pinned model leaves the deal's posture unchanged while arming the `ERR_STALE_UNDERWRITING_MODEL` gate at clear-to-close certification. Submitting a newer draft automatically supersedes any older `DRAFT` models on the deal, keeping at most one live draft.

### 3.4. The Purchase Agreement and the Diligence Clock

With at least one property on the deal and a latest underwriting model in `APPROVED` status, the analyst submits the deal for PSA drafting. A deal that is not in `SOURCING` is rejected with `ERR_DEAL_INVALID_STATE`; a deal with no property is rejected with `ERR_DEAL_NO_PROPERTY` (HTTP 422); a deal lacking an approved model is rejected with `ERR_NO_APPROVED_UNDERWRITING` (HTTP 422). These checks run after the generic existence and state checks of §2.8. Success moves the deal to `PSA_PENDING` and the posture to `UNDER_REVIEW`.

The analyst then drafts the purchase agreement with `psa_price_cents`, `earnest_money_cents`, `dd_period_days`, and `financing_contingency_days`. The diligence period must be at least 15 and at most 120 days; the financing contingency must be at least 0 and at most the diligence period plus 30 days; range violations are `ERR_FIELD_CONSTRAINT_VIOLATION`. The agreement starts in `DRAFT` with `amendment_count` zero.

Execution is the pivotal moment of the deal. The agreement must be in `DRAFT` (`ERR_PSA_NOT_EXECUTABLE`, HTTP 409), the deal must be in `PSA_PENDING`, the `psa_price_cents` must equal the deal's `purchase_price_cents` (else `ERR_PRICE_MISMATCH`, HTTP 409), and the `earnest_money_cents` must be at least one percent of the PSA price (else `ERR_EARNEST_MONEY_INSUFFICIENT`, HTTP 422). On execution the agreement's `executed_at` is stamped with the logical clock's current instant, the deal's `dd_period_end` is computed as `executed_at` plus `dd_period_days`, and the deal's `financing_contingency_end` is `executed_at` plus `financing_contingency_days`. The deal's `pinned_underwriting_model_id` is set to the latest approved model per §2.11, the deal moves to `PSA_EXECUTED`, its posture becomes `DD_OPEN`, and its `version` increments. In the same atomic step, the system auto-creates eight diligence milestones — one per `milestone_type`: `TITLE_REVIEW`, `SURVEY_REVIEW`, `ENVIRONMENTAL`, `PCA`, `ESTOPPEL_COLLECTION`, `SNDA_COLLECTION`, `FINANCING_COMMITMENT`, and `FINAL_WALKTHROUGH` — each in `PENDING` with its `due_date` set to the deal's `dd_period_end`. When the PSA carries a `financing_contingency_days` of zero — no financing contingency — the `FINANCING_COMMITMENT` milestone is created directly in `WAIVED`, since no loan is required.

An executed agreement can later be amended, cyclically: amending is permitted from `EXECUTED` or `AMENDED` alike, carries the OCC rule of §2.9 with `expected_psa_version`, and each amendment must keep the `earnest_money_cents` at least one percent of the new `psa_price_cents`. An amendment increments `amendment_count`, updates the deal's `purchase_price_cents` atomically to the new price, and increments the agreement's `version`. If the new price pushes a `SUBMITTED` financing application's loan above sixty-five percent of that price, the application cascades to `WITHDRAWN` in the same request — the loan-to-value ceiling is enforced not only at submission but against retrades.

### 3.5. Diligence Milestones

The eight auto-created milestones track the workstreams. A `DueDiligenceMilestone` records its `milestone_type`, `due_date`, the system-stamped `completed_at`, a `waived` flag defaulting to false, and its `status`. A milestone's `due_date` may never be set beyond the deal's `dd_period_end` (`ERR_MILESTONE_DUE_DATE_EXCEEDS_DD`, HTTP 422).

A diligence officer starts a milestone from `PENDING` while the deal is in `PSA_EXECUTED` or `DUE_DILIGENCE` (a wrong-state milestone yields `ERR_MILESTONE_INVALID_STATE`); starting the first milestone moves the deal itself from `PSA_EXECUTED` into `DUE_DILIGENCE`. Completion is normally automatic: each milestone type has an artifact gate — `TITLE_REVIEW` and `SURVEY_REVIEW` are satisfied when the title review reaches `CLEARED`; `ENVIRONMENTAL` when the environmental assessment reaches `CLEARED` or `CONDITIONAL`; `PCA` when the property condition assessment is `ACCEPTED`; `ESTOPPEL_COLLECTION` when all requested estoppel certificates are `CERTIFIED`; `SNDA_COLLECTION` when all requested SNDAs are `CERTIFIED`; `FINANCING_COMMITMENT` when a financing application is `COMMITTED` (or auto-waived at execution when there is no contingency); `FINAL_WALKTHROUGH` is satisfied only by manual completion. Automatic satisfaction works from `PENDING` directly — a title review cleared before anyone started the milestone still satisfies it — and stamps `completed_at` with the logical clock, then recomputes posture. Manual completion by an officer is the fallback path from `IN_PROGRESS` and likewise stamps `completed_at`.

The committee may waive a milestone from `PENDING` or `IN_PROGRESS`, which sets `waived` true; waived milestones count as satisfied for posture purposes. Two milestone types are never waivable — `TITLE_REVIEW` and `ENVIRONMENTAL` — and an attempt to waive either is rejected with `ERR_MILESTONE_NOT_WAIVABLE` (HTTP 422). Finally, if the logical clock passes a pending milestone's `due_date`, the milestone flips to `OVERDUE` and the deal posture drops to `DD_BLOCKED` (§2.6).

### 3.6. Title and Survey Review

A diligence officer opens a title review with the `title_company`, an optional `survey_type` of `ALTA` (the default), `BOUNDARY`, or `TOPOGRAPHIC`, and the `received_at` date of the title commitment. The review starts `RECEIVED` with an `exception_count` of zero. Beginning review moves it to `UNDER_REVIEW`; a review not in `RECEIVED` cannot be begun (`ERR_TITLE_REVIEW_INVALID_STATE`).

Exceptions are raised against a review in `UNDER_REVIEW` with an `exception_code` (the Schedule B-II code), a `severity` of `STANDARD`, `MATERIAL`, or `FATAL`, a `description`, an optional `cure_cost_cents` defaulting to zero, and an optional `cured_by_exception_id` used when the new exception is a revision that supersedes an already-cured one. Raising the first exception flips the review to `EXCEPTIONS_RAISED`, increments the review's `exception_count` — which counts linked exceptions in any non-resolved state — and, when the severity is `FATAL`, drops the deal posture to `DD_BLOCKED`. When `cured_by_exception_id` is supplied and names a `CURED` exception, that referenced exception is superseded to `SUPERSEDED` as the new one opens.

Curing proceeds in two steps. The officer proposes a cure, moving the exception from `OPEN` to `CURE_PROPOSED` (`ERR_EXCEPTION_INVALID_STATE` guards the from-state), then confirms the cure. Confirming a cure on a `MATERIAL` or `FATAL` exception whose `cure_cost_cents` exceeds 100,000 cents requires committee sign-off; without it the confirmation is rejected with `ERR_CURE_COST_NEEDS_COMMITTEE` (HTTP 422). A confirmed cure moves the exception to `CURED`, decrements the review's `exception_count`, recomputes the deal posture — curing the last `FATAL` exception may lift the deal out of `DD_BLOCKED` — and rechecks the title milestones. Alternatively, the committee may waive an exception outright, but only when its severity is not `FATAL`: waiving a `FATAL` exception is rejected with `ERR_FATAL_NOT_WAIVABLE` (HTTP 422). A waived exception likewise decrements `exception_count` and recomputes posture.

The review itself is cleared by the officer from `UNDER_REVIEW` or `EXCEPTIONS_RAISED`, but only when `exception_count` is zero — otherwise `ERR_UNRESOLVED_TITLE_EXCEPTIONS` (HTTP 422). Clearing satisfies both the `TITLE_REVIEW` and `SURVEY_REVIEW` milestones in one stroke and recomputes posture. Rejecting a review requires at least one `FATAL` exception on it — rejection without one is refused with `ERR_NO_FATAL_EXCEPTION` (HTTP 422) — and a rejected review pushes the deal posture to `DD_BLOCKED`.

### 3.7. Environmental and Physical Condition

Environmental assessments are ordered by the diligence officer with a `phase` of `PHASE_I` or `PHASE_II`, a `recognized_environmental_condition` flag, an optional `remediation_cost_cents` defaulting to zero, and an optional `reliance_letter_received` defaulting to false. The assessment starts `ORDERED`. Receiving the report requires the reliance letter: attempting to receive while `reliance_letter_received` is false is rejected with `ERR_RELIANCE_LETTER_REQUIRED` (HTTP 422). Wrong-state attempts on any environmental transition are `ERR_EA_INVALID_STATE`.

From `RECEIVED`, three outcomes exist. A clean report — `recognized_environmental_condition` false — is cleared by the officer, satisfying the `ENVIRONMENTAL` milestone and recomputing posture; attempting the plain clear when a recognized environmental condition is present is rejected with `ERR_REC_PRESENT` (HTTP 422). When a condition is present and a remediation plan has been costed — `remediation_cost_cents` greater than zero — the committee may mark the assessment `CONDITIONAL`, which also satisfies the `ENVIRONMENTAL` milestone (conditional counts as satisfied) and recomputes posture. When a condition is present and the deal cannot proceed, the officer fails the assessment: status `FAILED`, posture `DD_BLOCKED`.

The property condition assessment runs in parallel. It is ordered with `immediate_repair_cost_cents`, `capital_reserve_cents_per_sqft`, and a `condition_rating` of `GOOD`, `FAIR`, `POOR`, or `CRITICAL`. Receipt by the officer computes the `total_reserve_cents` as the `capital_reserve_cents_per_sqft` multiplied by the `rentable_sqft` of the linked property. Committee acceptance requires the rating not be `CRITICAL` — a `CRITICAL` rating is rejected with `ERR_PCA_CRITICAL_CONDITION` (HTTP 422) — and acceptance satisfies the `PCA` milestone. The committee may instead reject the assessment. Wrong-state transitions return `ERR_PCA_INVALID_STATE`.

### 3.8. Estoppels and SNDAs

Estoppel certificates are requested per deal with a payload naming the `lease_id` and `tenant_id`, the tenant-confirmed `rent_confirmed_cents`, and `default_confirmed` indicating whether the tenant confirms an absence of landlord default. Both referenced resources must exist (`ERR_REFERENCED_RESOURCE_NOT_FOUND`). The certificate starts `REQUESTED`. Receipt by the officer moves it to `RECEIVED` and pulls the lease into `ESTOPPEL_PENDING`. Wrong-state transitions are `ERR_ESTOPPEL_INVALID_STATE`.

Certification enforces two tenant-representation checks. First, `default_confirmed` must be true; a certificate disclosing a landlord default is rejected with `ERR_ESTOPPEL_DEFAULT_DISCLOSED` (HTTP 422). Second, the confirmed rent must sit within tolerance of the lease's `annual_base_rent_cents`: the absolute difference between `rent_confirmed_cents` and the lease rent, multiplied by ten thousand and divided by the lease rent, must be no more than fifty basis points — the boundary is inclusive, so a deviation of exactly 50 basis points passes — computed with round-half-up at basis-point precision. A wider deviation is rejected with `ERR_ESTOPPEL_RENT_MISMATCH` (HTTP 422). A failed certification attempt does not vanish: the certificate is recorded `DEFICIENT` with its `deficiency_reason` populated for audit, and the lease falls back from `ESTOPPEL_PENDING` to `VERIFIED` so a new certificate can be requested. Successful certification moves the certificate to `CERTIFIED`, the lease to `ESTOPPELED`, and rechecks the `ESTOPPEL_COLLECTION` milestone, which becomes satisfied when all requested certificates are certified. If the logical clock passes the deal's `dd_period_end` while a certificate is still `REQUESTED`, the certificate expires and its collection milestone goes `OVERDUE`.

SNDAs mirror the shape on the lender side. Requesting one names the `lease_id` and the `lender_name` whose non-disturbance is required, and records `non_disturbance_confirmed`. Receipt moves it to `RECEIVED`. Certification requires `non_disturbance_confirmed` true, else `ERR_SNDA_NON_DISTURBANCE_MISSING` (HTTP 422); certification rechecks the `SNDA_COLLECTION` milestone. The officer may instead reject a received SNDA. Wrong-state transitions are `ERR_SNDA_INVALID_STATE`.

### 3.9. Financing: Debt Service, LTV, and DSCR

A `CapitalMarketsOfficer` creates a financing application with a `loan_type` of `NEW_LOAN` or `ASSUMPTION`, the `loan_amount_cents`, the `interest_rate_bps`, and the `amortization_months` — zero meaning interest-only. The application starts `DRAFT`.

Submission validates the loan-to-value ceiling: the `loan_amount_cents` must be no more than sixty-five percent of the PSA's `psa_price_cents`, else `ERR_LTV_EXCEEDED` (HTTP 422). Submission then computes the annual debt service by one of two variants. For an interest-only loan (`amortization_months` zero), the `annual_debt_service_cents` is the loan amount multiplied by the `interest_rate_bps` and divided by ten thousand, rounded half up to whole cents. For an amortizing loan, the monthly rate is the `interest_rate_bps` divided by ten thousand and then by twelve; the constant monthly payment is the loan amount multiplied by that monthly rate and by the n-th power of one-plus-the-monthly-rate, divided by that same n-th power minus one, where n is the `amortization_months`; the payment is rounded half up to whole cents first, and the annual figure is that rounded payment multiplied by twelve — the pinned order matters and must not be reversed. For an `ASSUMPTION` loan, the `assumption_fee_cents` is one percent of the `loan_amount_cents`; for a `NEW_LOAN` it is zero.

Commitment is gated twice. The `dscr` — the latest approved model's `noi_cents` divided by the application's `annual_debt_service_cents`, carried to four decimal places with round-half-up — must be at least 1.25, with the boundary inclusive (exactly 1.25 passes); otherwise `ERR_DSCR_BELOW_MINIMUM` (HTTP 422). And the logical clock's current instant must be no later than the deal's `financing_contingency_end`; a commitment attempted after that date is rejected with `ERR_FINANCING_CONTINGENCY_LAPSED` (HTTP 422). Successful commitment stamps `committed_at` with the logical clock, satisfies the `FINANCING_COMMITMENT` milestone, and recomputes posture. The officer may instead decline a submitted application — terminal `DECLINED` — or withdraw one from `DRAFT` or `SUBMITTED` into `WITHDRAWN`. If the clock passes `financing_contingency_end` with the application still `SUBMITTED`, it lapses automatically, the milestone goes `OVERDUE`, and posture recomputes — possibly to `DD_BLOCKED`. An application invalidated by a PSA amendment's LTV cascade is withdrawn per §3.4. Invalid from-states on any of these transitions return `ERR_FINANCING_INVALID_STATE`.

### 3.10. Clear to Close, Closing, and Termination

When diligence is complete, the committee certifies the deal clear to close. The certification enforces seven gates, evaluated after the generic validation layers of §2.8: every milestone must be `SATISFIED` or `WAIVED` (else `ERR_MILESTONES_OUTSTANDING`); no title exception may sit in `OPEN` or `CURE_PROPOSED` with severity `FATAL` (else `ERR_FATAL_TITLE_EXCEPTION`); every non-waived environmental assessment must be `CLEARED` or `CONDITIONAL` (else `ERR_ENVIRONMENTAL_UNRESOLVED`); all required estoppel certificates must be `CERTIFIED` (else `ERR_ESTOPPEL_INCOMPLETE`); all required SNDAs must be `CERTIFIED` (else `ERR_SNDA_INCOMPLETE`); when financing is required, an application must be `COMMITTED` with its `committed_at` no later than `financing_contingency_end` (else `ERR_FINANCING_NOT_COMMITTED`); and the deal's `pinned_underwriting_model_id` must still be the latest approved model (else `ERR_STALE_UNDERWRITING_MODEL`). All seven are HTTP 422. On success the deal's posture and status become `CLEAR_TO_CLOSE` and the system issues the provisional closing statement in `DRAFT` with computed prorations, recording its `id` on the deal's `closing_statement_id`.

Closing itself is performed by the `EscrowOfficer` and requires the posture to be `CLEAR_TO_CLOSE` (else `ERR_NOT_CLEAR_TO_CLOSE`, HTTP 422) and the closing statement to be both `ISSUED` and `ACKNOWLEDGED` (else `ERR_CLOSING_STATEMENT_NOT_ACKNOWLEDGED`, HTTP 422). Closing moves the deal to `CLOSED` in both `status` and `posture`, sets `earnest_money_released` true — the deposit is released to the seller — and closes the purchase agreement.

Termination by the analyst is available from `DUE_DILIGENCE` or `CLEAR_TO_CLOSE` (and from `PSA_EXECUTED`); from any other state it is `ERR_DEAL_INVALID_STATE`. Termination takes a `termination_reason`; the deal and its posture become `TERMINATED`, the purchase agreement is terminated, all non-terminal milestones are waived by the system, and any financing application not yet `COMMITTED` is withdrawn. When the `termination_reason` is `BUYER_DEFAULT`, `earnest_money_released` is set true — the deposit is forfeited to the seller.

### 3.11. Closing Statements, Prorations, and True-Up

The provisional closing statement created at certification is issued by the escrow officer. Issuance requires the statement in `DRAFT` (else `ERR_STATEMENT_INVALID_STATE`) and the deal posture `CLEAR_TO_CLOSE`. The officer supplies the `closing_date` — which must not precede the agreement's `executed_at`, else `ERR_CLOSING_DATE_BEFORE_EXECUTION` (HTTP 422) — and a `proration_inputs` array of line descriptors, each carrying `line_type`, `lease_id`, `annual_amount_cents`, `period_start`, and `period_end`; each descriptor becomes one immutable `Proration` line. Line types are `BASE_RENT`, `CAM`, `TAX`, `INSURANCE`, or `UTILITY`; rent and CAM lines are per-lease, while tax and insurance lines reference the anchor lease of the property.

Each line's `prorated_cents` uses the ACT/365 day-count convention over the half-open interval from `period_start` (inclusive) to `period_end` (exclusive). The period length in days is the difference between `period_end` and `period_start`. Seller days are the days from `period_start` up to the earlier of `period_end` and the `closing_date`, floored at zero; buyer days are the period length minus seller days. The line amount is the `annual_amount_cents` multiplied by buyer days and divided by 365, rounded half up per line. The `direction` is `BUYER_CREDIT` for `BASE_RENT` and `CAM` lines — rent pre-paid by the tenant to the seller through the period end — and `SELLER_CREDIT` for the other line types.

The statement's `total_prorations_cents` is then the sum of the rounded per-line amounts with direction applied: buyer credits summed, seller credits summed, the latter subtracted from the former. The rounding order is pinned — round each line first, then sum; summing exact values and rounding once at the end produces different cents and is forbidden. The `cash_to_close_cents` composes in a pinned layered order: start from the `psa_price_cents`; subtract the financing application's `loan_amount_cents` (zero when there is no financing); add the `total_prorations_cents`, which may be negative; add the `assumption_fee_cents` (zero for a new loan or no financing); and finally subtract the `earnest_money_cents`. Each layer consumes the previous layer's result, so reordering is forbidden. Issuance computes all of these on the provisional variant, and the statement's `provisional` flag stays true until the true-up is finalized.

Acknowledgement by an analyst moves the statement from `ISSUED` to `ACKNOWLEDGED` under the segregation-of-duties rule of §2.10 against the issuing escrow officer. If the proration basis was computed on a stale view of the deal, the escrow officer reissues: the request carries `expected_deal_version` per §2.9 (mismatch rejected with `ERR_STALE_DEAL_VERSION`, HTTP 412), a fresh `closing_date`, and the same shape of `proration_inputs`; the old statement becomes `SUPERSEDED`, a new statement is created in `DRAFT` with `statement_version` incremented by one, and the deal's `version` increments. Statement versions are monotonic per deal.

After closing, the `AssetManager` proposes true-up adjustments with a `line_type` — the proration types plus `REPAIR_CREDIT` and `OTHER` — a signed `amount_cents` where positive means the buyer receives a credit, and a required `reason`. The adjustment starts `PROPOSED` with `approved` false. The escrow officer first moves it to `ESCROW_APPROVED` (or rejects it from `PROPOSED`); the asset manager then moves it to `FULLY_APPROVED`, which sets `approved` true and is segregation-of-duties checked against the proposing identity. Wrong-state attempts are `ERR_TRUE_UP_INVALID_STATE`.

Finalizing the true-up is the escrow officer's last act. It requires the deal `CLOSED` (else `ERR_DEAL_NOT_CLOSED`, HTTP 422) and every adjustment on the statement decided — each in `FULLY_APPROVED` or `REJECTED`, with anything left pending producing `ERR_TRUE_UP_PENDING` (HTTP 422). Finalization flips `provisional` to false, folds every fully-approved adjustment's `amount_cents` into a final-variant recompute of the prorations — the adjustments move to `APPLIED` in the same step — and recomputes `total_prorations_cents` and `cash_to_close_cents` under the same pinned rounding and layering rules. The statement lands in `TRUED_UP`.

### 3.12. Query Surface

Beyond the workflow operations, the API exposes a read surface for reporting and reverse reachability. Deals can be listed with filters on `status`, `posture`, and the back-reference fields `pinned_underwriting_model_id` and `closing_statement_id`, so a client can find the deal that pinned a given model or holds a given statement. Leases list with `status` and `tenant_id` filters; milestones with `status` and `milestone_type`; title reviews and exceptions with `status` — and exceptions additionally with `severity`, `title_review_id`, and `cured_by_exception_id`; environmental assessments with `status` and `phase`; estoppels with `lease_id`, `tenant_id`, `deal_id`, and `status`; SNDAs with `lease_id`, `deal_id`, and `status`; financing applications with `status` and `loan_type`; closing statements with `deal_id` and `status`; prorations with `closing_statement_id`, `lease_id`, and `line_type`; true-up adjustments with `closing_statement_id` and `status`; and flat property and model lists with `deal_id` and `status`. Flat single-resource fetches exist for properties, leases, models, title reviews and exceptions, estoppels, SNDAs, closing statements, prorations, and true-up adjustments, each returning the entity-specific 404 of §2.8 when the identifier does not exist.

## 4. Endpoint Definitions

Operations that create a new resource — a deal, tenant, property, lease, model, PSA, title review or exception, assessment, estoppel, SNDA, financing application, or true-up adjustment — return `201 Created`. Operations that transition or otherwise modify an existing resource return `200 OK`. All list endpoints paginate per §2.3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock; fires time-based system transitions | PlatformAdmin |
| POST | `/acquisition-deals/deals` | Create a new acquisition deal | AcquisitionsAnalyst |
| GET | `/acquisition-deals/deals` | List deals; filters on status, posture, pinned model, closing statement | All roles |
| GET | `/acquisition-deals/deals/{id}` | Get a specific deal | All roles |
| POST | `/acquisition-deals/deals/{id}/submit-for-psa` | Submit deal for PSA drafting | AcquisitionsAnalyst |
| POST | `/acquisition-deals/deals/{id}/certify-clear-to-close` | Committee certifies deal is clear to close | UnderwritingCommittee |
| POST | `/acquisition-deals/deals/{id}/close` | Close the deal | EscrowOfficer |
| POST | `/acquisition-deals/deals/{id}/terminate` | Terminate the deal | AcquisitionsAnalyst |
| POST | `/tenants` | Create a tenant | AcquisitionsAnalyst |
| GET | `/tenants` | List tenants | AcquisitionsAnalyst, UnderwritingCommittee, DueDiligenceOfficer, PlatformAdmin |
| GET | `/tenants/{id}` | Get a tenant | AcquisitionsAnalyst, UnderwritingCommittee, DueDiligenceOfficer, PlatformAdmin |
| POST | `/tenants/{id}/analyze-credit` | Analyze tenant credit | UnderwritingCommittee |
| POST | `/tenants/{id}/approve-credit` | Approve tenant credit | UnderwritingCommittee |
| POST | `/tenants/{id}/reject-credit` | Reject tenant credit | UnderwritingCommittee |
| POST | `/acquisition-deals/deals/{id}/properties` | Add a property to a deal | AcquisitionsAnalyst |
| GET | `/acquisition-deals/deals/{id}/properties` | List properties of a deal | All roles |
| GET | `/acquisition-deals/deals/{id}/properties/{propertyId}` | Get a property | All roles |
| POST | `/acquisition-deals/deals/{id}/properties/{propertyId}/mark-surveyed` | Mark property surveyed | DueDiligenceOfficer |
| POST | `/acquisition-deals/deals/{id}/properties/{propertyId}/clear` | Clear property | DueDiligenceOfficer |
| POST | `/acquisition-deals/deals/{id}/properties/{propertyId}/flag` | Flag property | DueDiligenceOfficer |
| POST | `/acquisition-deals/deals/{id}/properties/{propertyId}/leases` | Create a lease on a property | AcquisitionsAnalyst |
| GET | `/acquisition-deals/deals/{id}/properties/{propertyId}/leases` | List leases of a property | All roles |
| GET | `/acquisition-deals/deals/{id}/properties/{propertyId}/leases/{leaseId}` | Get a lease | All roles |
| POST | `/acquisition-deals/deals/{id}/properties/{propertyId}/leases/{leaseId}/verify` | Verify lease (tenant credit must be approved) | AcquisitionsAnalyst |
| POST | `/acquisition-deals/deals/{id}/underwriting-models` | Create an underwriting model | AcquisitionsAnalyst |
| GET | `/acquisition-deals/deals/{id}/underwriting-models` | List underwriting models for a deal | AcquisitionsAnalyst, UnderwritingCommittee, PlatformAdmin |
| GET | `/acquisition-deals/deals/{id}/underwriting-models/{modelId}` | Get an underwriting model | AcquisitionsAnalyst, UnderwritingCommittee, PlatformAdmin |
| POST | `/acquisition-deals/deals/{id}/underwriting-models/{modelId}/submit` | Submit model for committee review | AcquisitionsAnalyst |
| POST | `/acquisition-deals/deals/{id}/underwriting-models/{modelId}/approve` | Approve model (SoD vs submitter) | UnderwritingCommittee |
| POST | `/acquisition-deals/deals/{id}/underwriting-models/{modelId}/reject` | Reject model | UnderwritingCommittee |
| POST | `/acquisition-deals/deals/{id}/purchase-agreements` | Draft a PSA for a deal | AcquisitionsAnalyst |
| GET | `/acquisition-deals/deals/{id}/purchase-agreements` | List PSAs for a deal | All roles |
| GET | `/acquisition-deals/deals/{id}/purchase-agreements/{psaId}` | Get a PSA | All roles |
| POST | `/acquisition-deals/deals/{id}/purchase-agreements/{psaId}/execute` | Execute PSA | AcquisitionsAnalyst |
| POST | `/acquisition-deals/deals/{id}/purchase-agreements/{psaId}/amend` | Amend PSA price/terms (OCC on PSA version) | AcquisitionsAnalyst |
| GET | `/acquisition-deals/deals/{id}/milestones` | List milestones for a deal | AcquisitionsAnalyst, UnderwritingCommittee, DueDiligenceOfficer, EscrowOfficer, AssetManager, PlatformAdmin |
| GET | `/acquisition-deals/deals/{id}/milestones/{milestoneId}` | Get a milestone | AcquisitionsAnalyst, UnderwritingCommittee, DueDiligenceOfficer, EscrowOfficer, AssetManager, PlatformAdmin |
| POST | `/acquisition-deals/deals/{id}/milestones/{milestoneId}/start` | Start a milestone | DueDiligenceOfficer |
| POST | `/acquisition-deals/deals/{id}/milestones/{milestoneId}/complete` | Complete a milestone manually | DueDiligenceOfficer |
| POST | `/acquisition-deals/deals/{id}/milestones/{milestoneId}/waive` | Waive a milestone (TITLE_REVIEW/ENVIRONMENTAL not waivable) | UnderwritingCommittee |
| POST | `/acquisition-deals/deals/{id}/title-reviews` | Create a title review | DueDiligenceOfficer |
| GET | `/acquisition-deals/deals/{id}/title-reviews` | List title reviews | AcquisitionsAnalyst, UnderwritingCommittee, DueDiligenceOfficer, PlatformAdmin |
| GET | `/acquisition-deals/deals/{id}/title-reviews/{reviewId}` | Get a title review | AcquisitionsAnalyst, UnderwritingCommittee, DueDiligenceOfficer, PlatformAdmin |
| POST | `/acquisition-deals/deals/{id}/title-reviews/{reviewId}/begin-review` | Begin title review | DueDiligenceOfficer |
| POST | `/acquisition-deals/deals/{id}/title-reviews/{reviewId}/clear` | Clear title review (requires zero exceptions) | DueDiligenceOfficer |
| POST | `/acquisition-deals/deals/{id}/title-reviews/{reviewId}/reject` | Reject title review (requires a FATAL exception) | DueDiligenceOfficer |
| POST | `/acquisition-deals/deals/{id}/title-reviews/{reviewId}/exceptions` | Raise a title exception | DueDiligenceOfficer |
| GET | `/acquisition-deals/deals/{id}/title-reviews/{reviewId}/exceptions` | List exceptions of a review | AcquisitionsAnalyst, UnderwritingCommittee, DueDiligenceOfficer, PlatformAdmin |
| GET | `/acquisition-deals/deals/{id}/title-reviews/{reviewId}/exceptions/{exId}` | Get an exception | AcquisitionsAnalyst, UnderwritingCommittee, DueDiligenceOfficer, PlatformAdmin |
| POST | `/acquisition-deals/deals/{id}/title-reviews/{reviewId}/exceptions/{exId}/propose-cure` | Propose cure for an exception | DueDiligenceOfficer |
| POST | `/acquisition-deals/deals/{id}/title-reviews/{reviewId}/exceptions/{exId}/confirm-cure` | Confirm cure (committee sign-off if costly) | DueDiligenceOfficer |
| POST | `/acquisition-deals/deals/{id}/title-reviews/{reviewId}/exceptions/{exId}/waive` | Waive a non-FATAL exception | UnderwritingCommittee |
| POST | `/acquisition-deals/deals/{id}/environmental-assessments` | Order an environmental assessment | DueDiligenceOfficer |
| GET | `/acquisition-deals/deals/{id}/environmental-assessments` | List environmental assessments | AcquisitionsAnalyst, UnderwritingCommittee, DueDiligenceOfficer, PlatformAdmin |
| GET | `/acquisition-deals/deals/{id}/environmental-assessments/{eaId}` | Get an environmental assessment | AcquisitionsAnalyst, UnderwritingCommittee, DueDiligenceOfficer, PlatformAdmin |
| POST | `/acquisition-deals/deals/{id}/environmental-assessments/{eaId}/receive` | Receive EA report (requires reliance letter) | DueDiligenceOfficer |
| POST | `/acquisition-deals/deals/{id}/environmental-assessments/{eaId}/clear` | Clear EA (requires no REC) | DueDiligenceOfficer |
| POST | `/acquisition-deals/deals/{id}/environmental-assessments/{eaId}/mark-conditional` | Mark EA conditional (REC present with costed remediation) | UnderwritingCommittee |
| POST | `/acquisition-deals/deals/{id}/environmental-assessments/{eaId}/fail` | Fail EA (REC present) | DueDiligenceOfficer |
| POST | `/acquisition-deals/deals/{id}/property-condition-assessments` | Order a PCA | DueDiligenceOfficer |
| GET | `/acquisition-deals/deals/{id}/property-condition-assessments` | List PCAs | AcquisitionsAnalyst, UnderwritingCommittee, DueDiligenceOfficer, PlatformAdmin |
| GET | `/acquisition-deals/deals/{id}/property-condition-assessments/{pcaId}` | Get a PCA | AcquisitionsAnalyst, UnderwritingCommittee, DueDiligenceOfficer, PlatformAdmin |
| POST | `/acquisition-deals/deals/{id}/property-condition-assessments/{pcaId}/receive` | Receive PCA | DueDiligenceOfficer |
| POST | `/acquisition-deals/deals/{id}/property-condition-assessments/{pcaId}/accept` | Accept PCA (CRITICAL rating blocks) | UnderwritingCommittee |
| POST | `/acquisition-deals/deals/{id}/property-condition-assessments/{pcaId}/reject` | Reject PCA | UnderwritingCommittee |
| POST | `/acquisition-deals/deals/{id}/estoppels` | Request an estoppel certificate | DueDiligenceOfficer |
| GET | `/acquisition-deals/deals/{id}/estoppels` | List estoppels for a deal | AcquisitionsAnalyst, UnderwritingCommittee, DueDiligenceOfficer, PlatformAdmin |
| GET | `/acquisition-deals/deals/{id}/estoppels/{estoppelId}` | Get an estoppel | AcquisitionsAnalyst, UnderwritingCommittee, DueDiligenceOfficer, PlatformAdmin |
| POST | `/acquisition-deals/deals/{id}/estoppels/{estoppelId}/receive` | Receive estoppel from tenant | DueDiligenceOfficer |
| POST | `/acquisition-deals/deals/{id}/estoppels/{estoppelId}/certify` | Certify estoppel (rent tolerance and no-default checks) | DueDiligenceOfficer |
| POST | `/acquisition-deals/deals/{id}/sndas` | Request an SNDA | DueDiligenceOfficer |
| GET | `/acquisition-deals/deals/{id}/sndas` | List SNDAs for a deal | AcquisitionsAnalyst, UnderwritingCommittee, DueDiligenceOfficer, PlatformAdmin |
| GET | `/acquisition-deals/deals/{id}/sndas/{sndaId}` | Get an SNDA | AcquisitionsAnalyst, UnderwritingCommittee, DueDiligenceOfficer, PlatformAdmin |
| POST | `/acquisition-deals/deals/{id}/sndas/{sndaId}/receive` | Receive SNDA from lender | DueDiligenceOfficer |
| POST | `/acquisition-deals/deals/{id}/sndas/{sndaId}/certify` | Certify SNDA (non-disturbance required) | DueDiligenceOfficer |
| POST | `/acquisition-deals/deals/{id}/sndas/{sndaId}/reject` | Reject SNDA | DueDiligenceOfficer |
| POST | `/acquisition-deals/deals/{id}/financing-applications` | Create a financing application | CapitalMarketsOfficer |
| GET | `/acquisition-deals/deals/{id}/financing-applications` | List financing applications | AcquisitionsAnalyst, UnderwritingCommittee, CapitalMarketsOfficer, EscrowOfficer, PlatformAdmin |
| GET | `/acquisition-deals/deals/{id}/financing-applications/{appId}` | Get a financing application | AcquisitionsAnalyst, UnderwritingCommittee, CapitalMarketsOfficer, EscrowOfficer, PlatformAdmin |
| POST | `/acquisition-deals/deals/{id}/financing-applications/{appId}/submit` | Submit application (LTV check; computes debt service) | CapitalMarketsOfficer |
| POST | `/acquisition-deals/deals/{id}/financing-applications/{appId}/commit` | Commit loan (DSCR and contingency-window checks) | CapitalMarketsOfficer |
| POST | `/acquisition-deals/deals/{id}/financing-applications/{appId}/decline` | Decline application | CapitalMarketsOfficer |
| POST | `/acquisition-deals/deals/{id}/financing-applications/{appId}/withdraw` | Withdraw application | CapitalMarketsOfficer |
| GET | `/acquisition-deals/deals/{id}/closing-statements` | List closing statements for a deal | AcquisitionsAnalyst, UnderwritingCommittee, EscrowOfficer, AssetManager, CapitalMarketsOfficer, PlatformAdmin |
| GET | `/acquisition-deals/deals/{id}/closing-statements/{stmtId}` | Get a closing statement | AcquisitionsAnalyst, UnderwritingCommittee, EscrowOfficer, AssetManager, CapitalMarketsOfficer, PlatformAdmin |
| POST | `/acquisition-deals/deals/{id}/closing-statements/{stmtId}/issue` | Issue closing statement (computes provisional prorations) | EscrowOfficer |
| POST | `/acquisition-deals/deals/{id}/closing-statements/{stmtId}/acknowledge` | Acknowledge closing statement (SoD vs issuer) | AcquisitionsAnalyst |
| POST | `/acquisition-deals/deals/{id}/closing-statements/{stmtId}/reissue` | Reissue closing statement (OCC on deal version; supersedes old) | EscrowOfficer |
| POST | `/acquisition-deals/deals/{id}/closing-statements/{stmtId}/finalize-true-up` | Finalize post-closing true-up (final-variant prorations) | EscrowOfficer |
| GET | `/acquisition-deals/deals/{id}/closing-statements/{stmtId}/prorations` | List proration lines of a closing statement | AcquisitionsAnalyst, UnderwritingCommittee, EscrowOfficer, AssetManager, CapitalMarketsOfficer, PlatformAdmin |
| GET | `/acquisition-deals/deals/{id}/closing-statements/{stmtId}/prorations/{prorationId}` | Get a proration line | AcquisitionsAnalyst, UnderwritingCommittee, EscrowOfficer, AssetManager, CapitalMarketsOfficer, PlatformAdmin |
| POST | `/acquisition-deals/deals/{id}/closing-statements/{stmtId}/true-ups` | Propose a true-up adjustment | AssetManager |
| GET | `/acquisition-deals/deals/{id}/closing-statements/{stmtId}/true-ups` | List true-up adjustments | AcquisitionsAnalyst, UnderwritingCommittee, EscrowOfficer, AssetManager, PlatformAdmin |
| GET | `/acquisition-deals/deals/{id}/closing-statements/{stmtId}/true-ups/{adjId}` | Get a true-up adjustment | AcquisitionsAnalyst, UnderwritingCommittee, EscrowOfficer, AssetManager, PlatformAdmin |
| POST | `/acquisition-deals/deals/{id}/closing-statements/{stmtId}/true-ups/{adjId}/escrow-approve` | Escrow officer approves true-up | EscrowOfficer |
| POST | `/acquisition-deals/deals/{id}/closing-statements/{stmtId}/true-ups/{adjId}/asset-manager-approve` | Asset manager approves true-up (SoD vs proposer) | AssetManager |
| POST | `/acquisition-deals/deals/{id}/closing-statements/{stmtId}/true-ups/{adjId}/reject` | Reject true-up | EscrowOfficer |
| GET | `/acquisition-deals/properties/{id}` | Get a property by id (flat) | All roles |
| GET | `/acquisition-deals/properties` | List properties (flat); filter by deal | All roles |
| GET | `/acquisition-deals/leases/{id}` | Get a lease by id (flat) | All roles |
| GET | `/acquisition-deals/leases` | List leases (flat); filter by property or tenant | All roles |
| GET | `/acquisition-deals/underwriting-models/{id}` | Get an underwriting model by id (flat) | AcquisitionsAnalyst, UnderwritingCommittee, PlatformAdmin |
| GET | `/acquisition-deals/underwriting-models` | List underwriting models (flat); filter by deal | AcquisitionsAnalyst, UnderwritingCommittee, PlatformAdmin |
| GET | `/acquisition-deals/title-reviews/{id}` | Get a title review by id (flat) | AcquisitionsAnalyst, UnderwritingCommittee, DueDiligenceOfficer, PlatformAdmin |
| GET | `/acquisition-deals/title-exceptions/{id}` | Get a title exception by id (flat) | AcquisitionsAnalyst, UnderwritingCommittee, DueDiligenceOfficer, PlatformAdmin |
| GET | `/acquisition-deals/title-exceptions` | List title exceptions (flat); filter by review or supersession link | AcquisitionsAnalyst, UnderwritingCommittee, DueDiligenceOfficer, PlatformAdmin |
| GET | `/acquisition-deals/estoppels/{id}` | Get an estoppel by id (flat) | AcquisitionsAnalyst, UnderwritingCommittee, DueDiligenceOfficer, PlatformAdmin |
| GET | `/acquisition-deals/estoppels` | List estoppels (flat); filter by lease, tenant, or deal | AcquisitionsAnalyst, UnderwritingCommittee, DueDiligenceOfficer, PlatformAdmin |
| GET | `/acquisition-deals/sndas/{id}` | Get an SNDA by id (flat) | AcquisitionsAnalyst, UnderwritingCommittee, DueDiligenceOfficer, PlatformAdmin |
| GET | `/acquisition-deals/sndas` | List SNDAs (flat); filter by lease or deal | AcquisitionsAnalyst, UnderwritingCommittee, DueDiligenceOfficer, PlatformAdmin |
| GET | `/acquisition-deals/closing-statements/{id}` | Get a closing statement by id (flat) | AcquisitionsAnalyst, UnderwritingCommittee, EscrowOfficer, AssetManager, CapitalMarketsOfficer, PlatformAdmin |
| GET | `/acquisition-deals/closing-statements` | List closing statements (flat); filter by deal | AcquisitionsAnalyst, UnderwritingCommittee, EscrowOfficer, AssetManager, CapitalMarketsOfficer, PlatformAdmin |
| GET | `/acquisition-deals/prorations/{id}` | Get a proration line by id (flat) | AcquisitionsAnalyst, UnderwritingCommittee, EscrowOfficer, AssetManager, CapitalMarketsOfficer, PlatformAdmin |
| GET | `/acquisition-deals/prorations` | List proration lines (flat); filter by statement, lease, or line type | AcquisitionsAnalyst, UnderwritingCommittee, EscrowOfficer, AssetManager, CapitalMarketsOfficer, PlatformAdmin |
| GET | `/acquisition-deals/true-up-adjustments/{id}` | Get a true-up adjustment by id (flat) | AcquisitionsAnalyst, UnderwritingCommittee, EscrowOfficer, AssetManager, PlatformAdmin |
| GET | `/acquisition-deals/true-up-adjustments` | List true-up adjustments (flat); filter by statement | AcquisitionsAnalyst, UnderwritingCommittee, EscrowOfficer, AssetManager, PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 |
| `ERR_DEAL_NOT_FOUND` | 404 |
| `ERR_TENANT_NOT_FOUND` | 404 |
| `ERR_PROPERTY_NOT_FOUND` | 404 |
| `ERR_LEASE_NOT_FOUND` | 404 |
| `ERR_MODEL_NOT_FOUND` | 404 |
| `ERR_PSA_NOT_FOUND` | 404 |
| `ERR_MILESTONE_NOT_FOUND` | 404 |
| `ERR_TITLE_REVIEW_NOT_FOUND` | 404 |
| `ERR_EXCEPTION_NOT_FOUND` | 404 |
| `ERR_EA_NOT_FOUND` | 404 |
| `ERR_PCA_NOT_FOUND` | 404 |
| `ERR_ESTOPPEL_NOT_FOUND` | 404 |
| `ERR_SNDA_NOT_FOUND` | 404 |
| `ERR_FINANCING_NOT_FOUND` | 404 |
| `ERR_STATEMENT_NOT_FOUND` | 404 |
| `ERR_PRORATION_NOT_FOUND` | 404 |
| `ERR_TRUE_UP_NOT_FOUND` | 404 |
| `ERR_REFERENCED_RESOURCE_NOT_FOUND` | 422 |
| `ERR_DEAL_INVALID_STATE` | 409 |
| `ERR_MODEL_INVALID_STATE` | 409 |
| `ERR_PSA_NOT_EXECUTABLE` | 409 |
| `ERR_TITLE_REVIEW_INVALID_STATE` | 409 |
| `ERR_EXCEPTION_INVALID_STATE` | 409 |
| `ERR_EA_INVALID_STATE` | 409 |
| `ERR_PCA_INVALID_STATE` | 409 |
| `ERR_ESTOPPEL_INVALID_STATE` | 409 |
| `ERR_SNDA_INVALID_STATE` | 409 |
| `ERR_FINANCING_INVALID_STATE` | 409 |
| `ERR_STATEMENT_INVALID_STATE` | 409 |
| `ERR_TRUE_UP_INVALID_STATE` | 409 |
| `ERR_MILESTONE_INVALID_STATE` | 409 |
| `ERR_LEASE_INVALID_STATE` | 409 |
| `ERR_PROPERTY_INVALID_STATE` | 409 |
| `ERR_TENANT_CREDIT_INVALID_STATE` | 409 |
| `ERR_STALE_DEAL_VERSION` | 412 |
| `ERR_STALE_PSA_VERSION` | 412 |
| `ERR_SOD_VIOLATION` | 403 |
| `ERR_TENANT_CREDIT_NOT_APPROVED` | 422 |
| `ERR_RELIANCE_LETTER_REQUIRED` | 422 |
| `ERR_REC_PRESENT` | 422 |
| `ERR_FATAL_NOT_WAIVABLE` | 422 |
| `ERR_NO_FATAL_EXCEPTION` | 422 |
| `ERR_UNRATED_UNGUARANTEED_TENANT` | 422 |
| `ERR_FIELD_CONSTRAINT_VIOLATION` | 400 |
| `ERR_PRICE_MISMATCH` | 409 |
| `ERR_MILESTONE_DUE_DATE_EXCEEDS_DD` | 422 |
| `ERR_MILESTONE_NOT_WAIVABLE` | 422 |
| `ERR_ESTOPPEL_RENT_MISMATCH` | 422 |
| `ERR_ESTOPPEL_DEFAULT_DISCLOSED` | 422 |
| `ERR_SNDA_NON_DISTURBANCE_MISSING` | 422 |
| `ERR_EARNEST_MONEY_INSUFFICIENT` | 422 |
| `ERR_LTV_EXCEEDED` | 422 |
| `ERR_DSCR_BELOW_MINIMUM` | 422 |
| `ERR_CAP_RATE_OUT_OF_BAND` | 422 |
| `ERR_NOI_NON_POSITIVE` | 422 |
| `ERR_CURE_COST_NEEDS_COMMITTEE` | 422 |
| `ERR_FINANCING_CONTINGENCY_LAPSED` | 422 |
| `ERR_CLOSING_DATE_BEFORE_EXECUTION` | 422 |
| `ERR_DEAL_NO_PROPERTY` | 422 |
| `ERR_NO_APPROVED_UNDERWRITING` | 422 |
| `ERR_MILESTONES_OUTSTANDING` | 422 |
| `ERR_FATAL_TITLE_EXCEPTION` | 422 |
| `ERR_ENVIRONMENTAL_UNRESOLVED` | 422 |
| `ERR_ESTOPPEL_INCOMPLETE` | 422 |
| `ERR_SNDA_INCOMPLETE` | 422 |
| `ERR_FINANCING_NOT_COMMITTED` | 422 |
| `ERR_STALE_UNDERWRITING_MODEL` | 422 |
| `ERR_DEAL_NOT_CLOSED` | 422 |
| `ERR_TRUE_UP_PENDING` | 422 |
| `ERR_UNRESOLVED_TITLE_EXCEPTIONS` | 422 |
| `ERR_NOT_CLEAR_TO_CLOSE` | 422 |
| `ERR_CLOSING_STATEMENT_NOT_ACKNOWLEDGED` | 422 |
| `ERR_PCA_CRITICAL_CONDITION` | 422 |
