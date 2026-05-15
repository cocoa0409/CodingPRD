# Ad Delivery API — Product Requirements Document

## 1. Introduction

Modern internet advertising platforms operate at the intersection of multi-tenant account governance, real-time auction pricing, creative compliance review, and high-volume billing reconciliation. This document specifies the API for an end-to-end ad delivery platform that serves advertisers across general and regulated industries, runs auctions for both internal inventory and external exchange traffic, enforces creative review with a strict segregation between advertisers and reviewers, and maintains an authoritative wallet ledger from which each billable event is deducted as it finalises.

The platform must reconcile two competing pressures. On the operations side, advertisers and their campaign managers want fast iteration: rapid creative uploads, flexible budget and pacing controls, real-time visibility into spend, and the ability to recover from a rejection by filing an appeal. On the trust and safety side, the platform itself must ensure that medical, financial, and education advertisers carry verified qualifications; that compliant disclaimers accompany regulated creatives; that no reviewer ever decides on a creative belonging to their own advertiser; that no creative can be re-approved by the very reviewer who originally rejected it; and that invalid traffic is detected, reversed, and refunded with bookkeeping invariants intact.

The API exposed by this document is the single integration surface between five external actor classes — platform staff, advertiser-side users, ad exchanges, measurement partners, and the anti-fraud service — and the platform's persisted state. All paths described below are mounted under the platform's root; advertiser-scoped resources live under `/advertisers`, while auction events, billing events, conversions, and audit logs are mounted at their respective top-level paths.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two authentication headers, named exactly `X-User-ID` and `X-User-Role`. A request missing either header is rejected with `ERR_MISSING_USER_CONTEXT` and an HTTP 401 status. A request that carries both headers but whose role is unknown to the system, or whose role is not authorised for the requested operation, is rejected with `ERR_FORBIDDEN_ROLE` and an HTTP 403 status.

Eight roles are recognised by the platform. The exact strings the system accepts in `X-User-Role` are `PlatformAdmin`, `AccountOwner`, `CampaignManager`, `FinanceOfficer`, `CreativeReviewer`, `ExchangeService`, `MeasurementPartner`, and `AntiFraudService`.

Three of these roles are tied to a persisted advertiser-side user record. When `X-User-Role` is `AccountOwner`, `CampaignManager`, or `FinanceOfficer`, `X-User-ID` is interpreted as the `external_user_id` of an `AccountUser` row belonging to the advertiser scope of the request; ownership checks compare the resource's owning `advertiser_id` to the advertiser referenced by that `AccountUser`. The remaining five roles — `PlatformAdmin`, `CreativeReviewer`, `ExchangeService`, `MeasurementPartner`, and `AntiFraudService` — use an **opaque** identifier in `X-User-ID`. The opaque identifier is not tied to any persisted entity; the server may record it (for example, as `reviewer_user_id` on a `ReviewDecision` when a reviewer decides, or as `actor_user_id` on an `AuditLog` entry) but it does not compare it to any entity's `id` for ownership purposes.

The platform enforces a strict **segregation of duties** between reviewer identity and advertiser identity. A reviewer's `X-User-ID` MUST NOT equal any `external_user_id` belonging to an `AccountUser` of the creative's owning advertiser; if it does, the operation is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION` at HTTP 403. A reviewer who decides an appeal MUST NOT be the same `X-User-ID` recorded as the original rejection's reviewer; if it is, the operation is rejected with `ERR_APPEAL_SAME_REVIEWER` at HTTP 403.

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

All collection endpoints accept two query parameters, `limit` and `offset`. The default value of `limit` is 10; the minimum accepted value is 1 and the maximum accepted value is 100. The default value of `offset` is 0. Collections are sorted by `created_at` in ascending order. When a list endpoint returns, the response `meta` includes `limit`, `offset`, `total_count` (the total number of rows matching any filter, before pagination), and `has_more` (true when more rows exist beyond the current page).

### 2.4. Common Resource Properties and Optimistic Concurrency

Every persisted resource carries a server-minted `id` in the form of a UUID (no type-prefix prepended) and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. For most resources — `Advertiser`, `AccountUser`, `Campaign`, `AdGroup`, and `Creative` — the system additionally maintains an `updated_at` timestamp (ISO 8601 UTC, three fractional digits) refreshed on every mutation, and an integer `version` field that begins at 1 on creation and increments by 1 on every mutation.

Several resources carry only `id` and `created_at`, with no `updated_at` and no `version`: append-only ledgers and decision logs — namely `QualificationDoc`, `AuctionEvent`, `BillingEvent`, `ConversionEvent`, `WalletTransaction`, `ReviewDecision`, and `AuditLog`. For these entities the `updated_at` and `version` fields are absent from the resource representation entirely.

For resources that do carry `version`, the field is **optional** in any update or state-transition request body. When the client omits `version`, the server proceeds without an optimistic concurrency check. When the client includes `version`, the server compares it against the persisted value; on mismatch the operation is rejected with `ERR_INVALID_REQUEST` at HTTP 400. A successful mutation increments the `version` of the directly-mutated resource by 1; cascade-mutated relatives also bump their own `version` and `updated_at`.

### 2.5. Account, Campaign, Ad-Group, and Creative State Vocabulary

The platform tracks state machines on several entities. Every status string appears verbatim, in UPPERCASE, in API payloads.

- An `Advertiser` carries `status` in `PENDING`, `ACTIVE`, `SUSPENDED`, or `CLOSED`. It also carries an independent `qualification_status` in `UNVERIFIED`, `UNDER_REVIEW`, `VERIFIED`, or `REJECTED`, and a `balance_state` in `HEALTHY`, `LOW_BALANCE`, or `ZERO_BALANCE` — the latter is a parallel dimension to `status` and is recomputed on every wallet ledger movement.
- A `Campaign` carries `status` in `DRAFT`, `ACTIVE`, `PAUSED`, `BUDGET_EXHAUSTED`, or `ENDED`.
- An `AdGroup` carries `status` in `DRAFT`, `READY`, `RUNNING`, `PAUSED`, `DISAPPROVED`, `BUDGET_EXHAUSTED`, or `ARCHIVED`.
- A `Creative` carries `review_status` in `PENDING_PRESCREEN`, `PRESCREEN_FAILED`, `PENDING_HUMAN_REVIEW`, `APPROVED`, `REJECTED`, `APPEAL_FILED`, `UNDER_APPEAL_REVIEW`, or `ARCHIVED`.
- A `BillingEvent` carries `status` in `PENDING_IVT`, `VALID`, `INVALID_TRAFFIC`, `DEDUPLICATED`, `FINALIZED`, or `REVERSED`.
- A `WalletTransaction` carries `status` in `PENDING`, `SETTLED`, `FAILED`, or `REVERSED`, and `tx_type` in `RECHARGE`, `REFUND`, `ADJUSTMENT`, `INVOICE_SETTLEMENT`, or `CONSUMPTION`.
- A `ConversionEvent` carries `attribution_status` in `PENDING`, `ATTRIBUTED`, or `UNATTRIBUTED`.
- A `QualificationDoc` carries `review_status` in `PENDING`, `APPROVED`, or `REJECTED`.

Several enumerations live on input fields rather than status fields. `Advertiser.account_type` is one of `MCC`, `SUB_ACCOUNT`, or `INDEPENDENT`. `Advertiser.industry_category` is one of `GENERAL`, `MEDICAL`, `FINANCIAL`, or `EDUCATION`. `Advertiser.billing_mode` is one of `PREPAY` or `POSTPAY`. `AccountUser.account_role` is one of `OWNER`, `CAMPAIGN_MANAGER`, `FINANCE`, or `VIEWER`; the user's own `status` field is one of `ACTIVE` or `DISABLED` with a default of `ACTIVE`. `Campaign.pacing_strategy` is one of `STANDARD` or `ACCELERATED` with a default of `STANDARD`. `AdGroup.bidding_strategy` is one of `CPC`, `CPM`, `CPA`, or `OCPX`. `Creative.format` is one of `IMAGE`, `VIDEO`, `NATIVE`, or `HTML5`. `QualificationDoc.doc_type` is one of `BUSINESS_LICENSE`, `MEDICAL_PERMIT`, `FINANCIAL_LICENSE`, or `EDUCATION_PERMIT`. `BillingEvent.event_type` is one of `IMPRESSION`, `CLICK`, or `CONVERSION`. `ConversionEvent.source` is one of `WEB_PIXEL`, `APP_SDK`, `S2S`, or `OFFLINE_UPLOAD`, and its `attribution_model` is one of `LAST_CLICK`, `POSITION_BASED`, or `DATA_DRIVEN` with a default of `LAST_CLICK`. `AuctionEvent.exchange` is one of `INTERNAL` or `EXTERNAL_RTB`; `AuctionEvent.pricing_rule` is one of `GSP` or `VCG`; `AuctionEvent.device` is one of `DESKTOP`, `MOBILE`, `TABLET`, or `CTV`; and `AuctionEvent.outcome` is one of `FILLED`, `NO_BID`, `FLOOR_NOT_MET`, or `ALL_FILTERED`. `ReviewDecision.decision_type` is one of `PRESCREEN`, `HUMAN_REVIEW`, or `APPEAL_DECISION`, and its `outcome` is one of `APPROVE` or `REJECT`. `AuditLog.action` is one of `REVIEW_DECISION`, `BALANCE_ADJUSTMENT`, `REFUND`, `CREDIT_LINE_CHANGE`, or `ACCOUNT_STATUS_CHANGE`. The `AdGroup.targeting_device` field stores any subset of `DESKTOP`, `MOBILE`, `TABLET`, and `CTV`.

### 2.6. Nested Path Resolution

Many resources are addressed through nested paths — for example a creative under an ad-group under a campaign under an advertiser. Path parameters are resolved strictly left-to-right. If the first identifier in the path does not resolve, the system returns `ERR_ADVERTISER_NOT_FOUND` and does not attempt to resolve any further segment; if the second fails, `ERR_CAMPAIGN_NOT_FOUND`; then `ERR_AD_GROUP_NOT_FOUND`; then `ERR_CREATIVE_NOT_FOUND`. All four are returned at HTTP 404. The same left-to-right principle applies to `ERR_QUALIFICATION_DOC_NOT_FOUND`, `ERR_BILLING_EVENT_NOT_FOUND`, `ERR_CONVERSION_NOT_FOUND`, and `ERR_WALLET_TX_NOT_FOUND`.

### 2.7. Validation Priority Order

When several validation checks could fire on the same request, they are evaluated in a fixed order, and the first failure is the one returned. The ordering is: presence of `X-User-ID` and `X-User-Role` first, then role authorisation, then left-to-right path-parameter existence, then advertiser-level status (`ERR_ADVERTISER_SUSPENDED`, `ERR_ADVERTISER_CLOSED`, or `ERR_ADVERTISER_NOT_ACTIVE` as appropriate), then the resource's own state, then the business-safety checks for industry qualification and disclaimers, then the segregation-of-duties and appeal-segregation checks, then referential checks such as audience existence, then the business-constraint checks (frequency-cap minimum, non-empty auction pool, billing-event dedup), then temporal checks (attribution window, campaign date order), and finally the fiscal checks (budget shape, credit-line shape, refund-floor protection, adjustment-balance sufficiency, zero-balance activation block).

In particular, advertiser-level status is checked **before** the resource's own state. A request to pause an `AdGroup` whose parent advertiser is `SUSPENDED` will report `ERR_ADVERTISER_SUSPENDED`, not `ERR_INVALID_AD_GROUP_STATE`, regardless of which check the implementer happens to evaluate first internally.

### 2.8. Cascading State and Update Semantics

State transitions on parent entities cascade to children **synchronously** within the same request, in a deterministic top-down order. Every entity touched by a cascade has its `version` incremented and its `updated_at` refreshed; cascade-affected `WalletTransaction`, `BillingEvent`, `ReviewDecision`, `AuctionEvent`, `QualificationDoc`, and `AuditLog` rows (which carry no `version`) have only their `created_at` set on insertion and are otherwise immutable.

Three cascade depths arise in this system. Suspending an advertiser cascades to depth 2: every `RUNNING` `Campaign` becomes `PAUSED`, and every `RUNNING` `AdGroup` under those campaigns becomes `PAUSED`. Closing an advertiser cascades to depth 3: every `Campaign` becomes `ENDED`, every `AdGroup` under those campaigns becomes `ARCHIVED`, and every `Creative` under those ad-groups becomes `ARCHIVED`. Reinstating an advertiser does NOT auto-resume any campaign or ad-group; the operator must explicitly resume them.

### 2.9. Precision, Rounding, and the Wallet Ledger Discipline

All monetary amounts in this system are integer cents — `daily_budget_cents`, `lifetime_budget_cents`, `bid_cents`, `floor_price_cents`, `clearing_price_cents`, `gross_cost_cents`, `tax_cents`, `cost_cents`, `balance_cents`, `consumed_cents`, `credit_line_cents`, `low_balance_threshold_cents`, `amount_cents`, and `value_cents`. There is never a fractional cent in any payload, computed total, or balance. Where an algorithm operates on a real-valued sub-expression — a quality score, a predicted click-through rate, an attribution fraction, an IVT score — the system keeps real values in IEEE-754 double precision during intermediate computation and converts to integer cents only at the points the formula specifies (typically with `floor` for tax-style truncation, `ceil` for the GSP bid-just-to-beat step, and `round_half_up` for the advertiser risk score).

Wallet accounting follows a strict invariant: a forward `WalletTransaction` and its reversal must produce a net change of zero to `balance_cents`. The same invariant applies to a `BillingEvent` that finalises and is later reversed: the `CONSUMPTION` `WalletTransaction` plus its corresponding `REFUND` `WalletTransaction` net to zero. The wallet is therefore an append-only ledger; `balance_cents` and `consumed_cents` on `Advertiser` are pure derivations from the `WalletTransaction` table, never independently mutated.

## 3. Business Logic & Workflows

### 3.1. Onboarding an Advertiser and Verifying Qualifications

A `PlatformAdmin` brings a new advertiser onto the platform by creating an `Advertiser` record with its `account_type`, `legal_name`, `business_license_number`, `industry_category`, and `billing_mode`. Optional fields at creation are the `parent_account_id` (which is non-null only when `account_type` is `SUB_ACCOUNT`, linking to an `MCC` parent's `id`; top-level `MCC` accounts and `INDEPENDENT` accounts leave it null), the `credit_line_cents` (which defaults to 0 and is required to remain at 0 when `billing_mode` is `PREPAY`), the `low_balance_threshold_cents` (which defaults to 10000 — that is, one hundred dollars worth of cents), and the `tax_rate_bps` (which defaults to 0 and is expressed in basis points where ten thousand equals one hundred percent). The system also stamps each advertiser with a global monotonic `created_seq` used for FIFO tie-breaking elsewhere in the platform.

The new advertiser is born in `PENDING` status with `qualification_status` set to `UNVERIFIED`. To clear qualification, the advertiser uploads documents through their owner: an upload submits a `doc_type`, `doc_url`, and `expiry_date`, persisting a `QualificationDoc` in `review_status` of `PENDING` and advancing the parent advertiser's `qualification_status` to `UNDER_REVIEW`. A platform reviewer then decides the document, supplying an `outcome` and, on rejection, a `rejection_reason`; the document moves to `APPROVED` or `REJECTED`, and the parent's `qualification_status` is recomputed: when all required documents are `APPROVED` it becomes `VERIFIED`, and when any one is `REJECTED` it flips to `REJECTED`. The first time `qualification_status` reaches `VERIFIED` while the cumulative sum of `balance_cents` and `credit_line_cents` is strictly greater than zero, the advertiser transitions from `PENDING` to `ACTIVE`. If a later re-verification flips `qualification_status` back to `REJECTED` from a prior `VERIFIED`, the system cascades all currently-`APPROVED` creatives under the advertiser to `REJECTED`, decrementing the affected `approved_creative_count` on each parent ad-group accordingly.

Regulated industries require additional paperwork. For any advertiser whose `industry_category` is not `GENERAL`, the `special_qualifications` array must reference at least one approved industry-specific document — a `MEDICAL_PERMIT` for `MEDICAL`, a `FINANCIAL_LICENSE` for `FINANCIAL`, or an `EDUCATION_PERMIT` for `EDUCATION` — before any creative may be submitted. A creative upload attempted while `qualification_status` is anything other than `VERIFIED` for a regulated industry is rejected with `ERR_QUALIFICATION_REQUIRED`.

Once the advertiser is in `ACTIVE`, a `PlatformAdmin` may later suspend it (transitioning `status` to `SUSPENDED`), reinstate it back to `ACTIVE`, or close it (transitioning `status` to `CLOSED`). Suspension also fires when a re-verification flips `qualification_status` to `REJECTED`. Suspension cascades: every `Campaign` currently `RUNNING` is moved to `PAUSED`, and every `AdGroup` under it that was `RUNNING` is moved to `PAUSED`; an `AuditLog` entry is recorded with `action` equal to `ACCOUNT_STATUS_CHANGE`. Reinstatement returns the advertiser to `ACTIVE` (with a precondition that `qualification_status` is `VERIFIED`), records a matching audit entry, and leaves all campaigns and ad-groups in their `PAUSED` state — the operator must explicitly resume them. Closure requires that no `Campaign` is currently in `ACTIVE` or `RUNNING`; if any is, the close operation is rejected with `ERR_CANNOT_CLOSE_WITH_ACTIVE_CAMPAIGNS`. When closure proceeds, the cascade is deeper: all campaigns transition to `ENDED`, all ad-groups under those campaigns transition to `ARCHIVED`, and all creatives under those ad-groups transition to `ARCHIVED`. The path from `ACTIVE` or `SUSPENDED` to `CLOSED` is the only one that reaches the terminal state. An advertiser update from a `PlatformAdmin` may revise `credit_line_cents`, `low_balance_threshold_cents`, and `tax_rate_bps`; a change to `credit_line_cents` writes an `AuditLog` entry with `action` equal to `CREDIT_LINE_CHANGE`. Combinations of `credit_line_cents` and `billing_mode` are validated together: a non-zero credit line is permitted only when `billing_mode` is `POSTPAY`, and a `PREPAY` advertiser must keep `credit_line_cents` at exactly 0; violations are reported with `ERR_INVALID_CREDIT_LINE`.

### 3.2. Account Users and Role Mapping

Within an advertiser, an `AccountOwner` or `PlatformAdmin` adds individual users by recording an `external_user_id` and an `account_role`. The `external_user_id` is the stable string the user will later present in their `X-User-ID` header; the `account_role` selects which advertiser-side role the user is granted (`OWNER`, `CAMPAIGN_MANAGER`, `FINANCE`, or `VIEWER`). A subsequent patch on the same `AccountUser` may change either `account_role` or the user-level `status` (toggling between `ACTIVE` and `DISABLED`).

This mapping is the bridge the segregation-of-duties check relies on. When a `CreativeReviewer` decides on a creative, the system reads the creative's `advertiser_id`, looks up every `AccountUser.external_user_id` under that advertiser, and rejects with `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403) if the reviewer's `X-User-ID` matches any of them. This check applies to human-review approvals, human-review rejections, and appeal decisions — both `APPROVE` and `REJECT` outcomes on either decision endpoint.

### 3.3. Campaign and Ad-Group Lifecycle

A `CampaignManager` or `AccountOwner` creates a `Campaign` against the advertiser by supplying a `name`, a `daily_budget_cents`, a `pacing_strategy`, and a `start_date`, with optional `lifetime_budget_cents` (defaulting to null, meaning unlimited) and `end_date` (defaulting to null, meaning open-ended). Budgets are constrained: `daily_budget_cents` must be at least 100 (one dollar in cents), and if `lifetime_budget_cents` is set it must be greater than or equal to `daily_budget_cents`; violations return `ERR_INVALID_BUDGET`. Dates are constrained: when `end_date` is non-null, `start_date` must be on or before `end_date`; otherwise the request is rejected with `ERR_INVALID_CAMPAIGN_DATES`. The campaign is created in `DRAFT` and stamped with an account-scoped monotonic `created_seq`.

A subsequent update may alter `name`, `daily_budget_cents`, `lifetime_budget_cents`, `pacing_strategy`, or `end_date`; the same budget shape rule is re-validated. If the new `daily_budget_cents` is less than the campaign's accumulated `today_spent_cents`, the campaign immediately enters `BUDGET_EXHAUSTED`. Activation of a campaign — `DRAFT → ACTIVE` or `PAUSED → ACTIVE` — requires that the advertiser is currently `ACTIVE` and that at least one of the campaign's ad-groups has `approved_creative_count` of at least 1; in addition, activating from `PAUSED` requires that the advertiser's `balance_state` is either `HEALTHY` or `LOW_BALANCE` (i.e., not `ZERO_BALANCE`). Activating when `balance_state` equals `ZERO_BALANCE` is rejected with `ERR_ZERO_BALANCE` (HTTP 402). A campaign is paused either by explicit operator action or by cascade — from an advertiser suspension or close, or from a pause-on-zero balance event; pausing cascades to every `RUNNING` `AdGroup` under the campaign. Ending the campaign — `DRAFT/ACTIVE/PAUSED/BUDGET_EXHAUSTED → ENDED` — also happens by operator action, by cascade from an advertiser close, or by the system observing the current logical clock crossing the campaign's `end_date`; ending cascades to archive every ad-group and then every creative beneath them.

An ad-group is created under a campaign with a `name`, `bidding_strategy`, `bid_cents`, `targeting_geo` (an array of ISO 3166-2 codes), and optional targeting fields: `targeting_demographic` (an object holding `age_min`, `age_max`, and `genders`), `targeting_interest` (an array of taxonomy ids), `targeting_behavior` (an array of taxonomy ids), `targeting_device` (an array drawn from `DESKTOP`, `MOBILE`, `TABLET`, `CTV`), `targeting_dayparts` (an array of objects each holding `dow`, `hour_start`, and `hour_end`; empty means always-on), `remarketing_audience_id` (an audience reference; null when not remarketing), and `frequency_cap_per_user_per_day` (an integer of at least 1; null means no cap; values below 1 are rejected with `ERR_INVALID_FREQUENCY_CAP`). If `remarketing_audience_id` is supplied but does not reference a known audience, the request is rejected with `ERR_AUDIENCE_NOT_FOUND`. Each new ad-group starts in `DRAFT`, with `quality_score` initialised to 5.0 and `predicted_ctr` initialised to 0.02. Updates may revise the name, the bid, any of the targeting fields, the frequency cap, the `quality_score`, or the `predicted_ctr`.

Ad-group status follows the creative pipeline. An ad-group in `DRAFT` advances automatically to `READY` once its `approved_creative_count` is at least 1, and conversely drops to `DISAPPROVED` from `READY` or `RUNNING` if all creatives are rejected or archived and the count falls to 0; once a fresh creative is approved and the count returns to at least 1, the ad-group goes back to `READY`. An ad-group is activated to `RUNNING` only when its parent campaign is `ACTIVE` and `approved_creative_count` is at least 1; activation from `PAUSED` requires the same plus an advertiser-level check of `ACTIVE` status. Pausing moves an ad-group out of `RUNNING` either by explicit action or by cascade from a campaign pause, a campaign suspension, an advertiser suspension, or a pause-on-zero balance. Archiving an ad-group — from any non-archived state, by operator action or as a cascade from a campaign end — cascades to archive every non-archived creative beneath it.

### 3.4. Creative Submission, Review, and Appeals

An advertiser-side user uploads a `Creative` to a specific ad-group, supplying a `format`, an `asset_url`, a `headline`, a `body_text`, a `landing_url`, an optional `required_disclaimer`, and an optional `parent_version_id` (set when the upload revises a prior creative). The system stamps the new creative with a `version_number`: when `parent_version_id` is null, `version_number` starts at 1; when `parent_version_id` references a prior creative, the new `version_number` is the parent's `version_number` plus 1. The system also denormalises the owning `advertiser_id` onto the creative for cross-aggregate queries. The creative's `appeal_count` begins at 0; `archived_at` is null until archival; the `rejection_codes` array starts empty.

Two compliance rules guard creative submission. The first is the qualification gate: for any advertiser whose `industry_category` is `MEDICAL`, `FINANCIAL`, or `EDUCATION`, the creative may be submitted only when the advertiser's `qualification_status` equals `VERIFIED`; otherwise the upload is rejected with `ERR_QUALIFICATION_REQUIRED`. The second is the disclaimer gate: when `industry_category` is one of those three regulated categories, `required_disclaimer` must be present and non-empty. A missing or empty disclaimer is rejected with `ERR_DISCLAIMER_REQUIRED` both at submission and at human-review approval time — the second check exists to prevent a reviewer from approving a regulated creative that somehow slipped through with an empty disclaimer.

The creative enters review in `PENDING_PRESCREEN`. The pre-screen pipeline records a `pre_screen_score` between 0.0 and 1.0 produced by the automated screener and transitions the creative. If `pre_screen_score` is at least 0.8, the creative moves to `PRESCREEN_FAILED` and a `ReviewDecision` is recorded with `decision_type` `PRESCREEN` and `outcome` `REJECT`. If `pre_screen_score` is strictly less than 0.5, the creative moves to `PENDING_HUMAN_REVIEW` with a `ReviewDecision` recorded with `decision_type` `PRESCREEN` and `outcome` `APPROVE`. If `pre_screen_score` is in the half-open interval starting at 0.5 inclusive and ending at 0.8 exclusive — the borderline band — the creative also moves to `PENDING_HUMAN_REVIEW`, but the recorded `PRESCREEN` decision carries `notes` set to `borderline` to flag it for the human reviewer. The pre-screen endpoint also accepts an explicit `outcome` override: an outcome of `FAIL` forces `PRESCREEN_FAILED`, and an outcome of `PASS` forces `PENDING_HUMAN_REVIEW`. In all three score bands, the reviewer for the recorded `ReviewDecision` is the string `system`.

From `PENDING_HUMAN_REVIEW`, a `CreativeReviewer` decides the creative by supplying an `outcome` and optionally `rejection_codes` and `notes`. An `APPROVE` outcome moves the creative to `APPROVED`, increments the parent ad-group's `approved_creative_count`, records a `ReviewDecision` with `decision_type` of `HUMAN_REVIEW`, and emits an `AuditLog` entry with `action` of `REVIEW_DECISION`. A `REJECT` outcome moves the creative to `REJECTED`, requires that the supplied `rejection_codes` array is non-empty, persists those codes both onto the creative's own `rejection_codes` field and onto the `ReviewDecision`, and likewise writes an `AuditLog` entry. The segregation-of-duties check applies to both outcomes.

A rejected creative — whether the rejection came from pre-screen (`PRESCREEN_FAILED`) or human review (`REJECTED`) — may be appealed exactly once by a `CampaignManager` or `AccountOwner`. The appeal is rejected with `ERR_APPEAL_ALREADY_FILED` if `appeal_count` is already 1; on success the creative moves to `APPEAL_FILED` and `appeal_count` is set to 1. A reviewer accepts the appeal for review, moving the creative to `UNDER_APPEAL_REVIEW`. The reviewer then decides the appeal with an `outcome` and optional `rejection_codes`/`notes`. An `APPROVE` outcome here moves the creative to `APPROVED`, increments the parent ad-group's `approved_creative_count`, records a `ReviewDecision` with `decision_type` `APPEAL_DECISION` and `outcome` `APPROVE`, and writes an `AuditLog`. A `REJECT` outcome moves the creative to `REJECTED`, records an `APPEAL_DECISION` `ReviewDecision`, and writes an `AuditLog`. The appeal decider MUST NOT be the same `X-User-ID` recorded as `reviewer_user_id` on the original `HUMAN_REVIEW` rejection; an attempt by the same reviewer is rejected with `ERR_APPEAL_SAME_REVIEWER`.

Archiving a creative — either by operator action or by cascade from ad-group archival — moves the creative to `ARCHIVED`, sets its `archived_at` to the current server time, and, if the creative was previously `APPROVED`, decrements the parent ad-group's `approved_creative_count`. The ad-group's status is then re-evaluated: a drop from `READY` or `RUNNING` to a zero count flips it to `DISAPPROVED`.

Two reviewers attempting to decide the same creative in `PENDING_HUMAN_REVIEW` simultaneously must serialise: at most one approval is persisted, and the loser receives `ERR_REVIEW_ALREADY_DECIDED` (HTTP 409). When an approval and an archival happen simultaneously on a creative in `PENDING_HUMAN_REVIEW`, exactly one wins and the loser receives `ERR_INVALID_CREATIVE_STATE`. The system exposes the full decision history for any creative through a list of `ReviewDecision` records for audit; each record carries the `creative_id` it pertains to and the `reviewer_user_id` who recorded it.

Every administrative action that changes financial posture or account status is recorded as an `AuditLog` entry. The entry captures the `actor_user_id` and the `actor_role` (the `X-User-Role` at the time of the action), the affected `target_entity_type` and `target_entity_id`, and a pair of structured snapshots — `before_value` and `after_value` — recording the relevant fields immediately before and immediately after the change. System-driven actions (cascades, automatic state changes) record an `actor_user_id` of `system`.

### 3.5. The Auction Engine

When an inventory opportunity arrives, an `ExchangeService` (or a `PlatformAdmin` running a test auction) submits an auction request specifying the `exchange`, the `pricing_rule`, the `floor_price_cents` (the reserve price), the `user_id` (the end-user identifier used for frequency capping and identity stitching), the `device`, the `geo`, and an array of `candidate_ad_group_ids` eligible to bid. If `candidate_ad_group_ids` is empty, the request is rejected with `ERR_EMPTY_AUCTION_POOL`.

The auction proceeds through three stages. The first stage **filters** the candidate pool: ad-groups that fail brand-safety, that fail their own budget posture (parent campaign `BUDGET_EXHAUSTED`), or that fail the frequency-cap check are excluded, and their ids are recorded in `filtered_ad_group_ids`. The frequency-cap check counts, for the given `user_id` and candidate ad-group, every `BillingEvent` whose `ad_group_id` matches, whose `event_type` is `IMPRESSION`, whose `status` is either `VALID` or `FINALIZED`, whose underlying auction's `user_id` matches, and whose `finalized_at` is on or after the start of the current UTC day. When the ad-group's `frequency_cap_per_user_per_day` is non-null, the candidate is excluded when the count of those impressions is greater than or equal to the cap; the boundary is inclusive, so a count exactly equal to the cap excludes, while a count of cap minus 1 still admits one more impression.

The second stage **ranks** the surviving candidates. For each candidate ad-group, the system first computes an effective per-impression bid: for `CPC`, `CPA`, and `OCPX` bidding strategies the effective bid in cents equals the ad-group's `bid_cents`; for the `CPM` bidding strategy the effective bid in cents equals `bid_cents` divided by 1000, because `bid_cents` for CPM is expressed per thousand impressions. The ranking score for the candidate is then the product of three terms: the effective bid in cents, the candidate's `quality_score`, and the candidate's `predicted_ctr`. Quality scores are maintained in the closed real interval from 1.0 to 10.0; predicted CTR is in the closed real interval from 0.0 to 1.0. Candidates are sorted by ranking score in descending order; ties are broken by smaller `created_seq` first (older campaign wins).

The third stage **prices** the winner. If after filtering and ranking no candidate remains, the auction's `outcome` is set to `NO_BID` when no candidate ever existed, `ALL_FILTERED` when at least one existed but all were filtered, or `FLOOR_NOT_MET` when the winning candidate's effective bid was below `floor_price_cents`. Otherwise `outcome` is `FILLED`, `winning_ad_group_id` is set, and `winning_creative_id` selects an APPROVED creative under the winning ad-group. The unit clearing price depends on `pricing_rule`. Under `GSP`, if no runner-up exists, the unit clearing price in cents is exactly the `floor_price_cents`. If a runner-up exists, the system computes the bid-just-to-beat figure — the runner-up's ranking score divided by the product of the winner's `quality_score` and `predicted_ctr` — then rounds that quotient up to the nearest whole cent and adds 1, before clamping the result to be at least `floor_price_cents` and at most the winner's effective bid. The clamping order is fixed: GSP raw price first, then floor enforcement, then bid-shading. Under `VCG`, the same externality quotient is rounded up to the nearest whole cent — but with no `+1` cent adjustment and no shading — before being clamped to be at least the floor and at most the winner's effective bid. So for identical inputs, GSP and VCG can produce different clearing prices: in a scenario where the winner's ranking score is 80, the runner-up's ranking score is 60, and the product of the winner's `quality_score` and `predicted_ctr` is 10, GSP yields a clearing price of 7 cents (the ceiling of 6 plus 1), while VCG yields 6 cents (just the ceiling of 6).

Bid-shading applies only to `EXTERNAL_RTB` exchanges running `GSP`. After floor enforcement, the clearing unit price is multiplied by the shading factor of 0.92 and the result is rounded down to a whole cent; `bid_shaded` is set to true. Internal-inventory auctions and any VCG auctions are never shaded. The resulting `AuctionEvent` records the chosen `pricing_rule`, the computed `clearing_price_cents`, the filtered list, the winner, and the `outcome`.

### 3.6. Impression-and-Click Billing and Invalid-Traffic Detection

After an auction fills, the exchange or the measurement partner reports billable events back to the platform. An ingest supplies an `event_type`, the originating `auction_event_id`, the `ad_group_id` to charge, a `dedup_key` (a source-provided token unique per combination of `event_type` and `auction_event_id`), and an `ivt_score` between 0.0 and 1.0 supplied by the anti-fraud service. The system stamps the event with its denormalised `campaign_id` and `advertiser_id`. Each billing event progresses through a small status machine.

The first check is deduplication. If a prior `BillingEvent` already exists with the same combination of `event_type`, `auction_event_id`, and `dedup_key`, the new ingest is set to `DEDUPLICATED` rather than persisting a second row; the API returns HTTP 409 with `ERR_DUPLICATE_BILLING_EVENT`. The second check is the IVT screen. When `ivt_score` is strictly greater than 0.7, the event transitions to `INVALID_TRAFFIC` and no charge is applied; when `ivt_score` is at most 0.7, the event transitions to `VALID`.

A `VALID` event finalises immediately in the same request. Finalisation computes the charge. The charge depends on the ad-group's `bidding_strategy` and the event's `event_type` together: a `CPC` strategy charges only on `CLICK` events; a `CPM` strategy charges only on `IMPRESSION` events; a `CPA` strategy charges only on `CONVERSION` events; an `OCPX` strategy charges on `CLICK` events when configured for click optimisation and on `CONVERSION` events when configured for conversion optimisation, with the `event_type` value disambiguating at ingest time. When the strategy does not match the event type, `gross_cost_cents` is set to 0 — the event is still logged and finalised, but the charge is zero. When the strategy does match, `gross_cost_cents` is set to the `clearing_price_cents` from the referenced `AuctionEvent`. From there, `tax_cents` is computed as `gross_cost_cents` multiplied by the advertiser's `tax_rate_bps` divided by 10000 (basis points to fraction), truncated down to a whole cent. The total `cost_cents` is then `gross_cost_cents` plus `tax_cents`. The rounding order is fixed: tax is computed on the gross, then added — tax is never applied to a running total. The system then sets `finalized_at`, creates a `WalletTransaction` with `tx_type` of `CONSUMPTION` and `amount_cents` equal to the negative of `cost_cents`, decreases the advertiser's `balance_cents` by `cost_cents`, increases the advertiser's `consumed_cents` by `cost_cents`, increases the parent campaign's `lifetime_spent_cents` and `today_spent_cents` by `cost_cents`, re-evaluates budget exhaustion, and recomputes the advertiser's `balance_state`.

A finalised event can later be reversed by the anti-fraud service or a platform admin — typically because a late IVT classification reclassifies the traffic as invalid. Reversal supplies a `reversal_reason` (required, non-empty) and stores it on the event; the event moves to `REVERSED`, a compensating `WalletTransaction` with `tx_type` of `REFUND` and `amount_cents` equal to the positive of `cost_cents` is created, the advertiser's `balance_cents` is increased by `cost_cents`, `consumed_cents` is decreased by `cost_cents`, the campaign's lifetime and today spend totals are decreased, and budget posture is re-evaluated. The forward-plus-reverse pair leaves `balance_cents` unchanged in net.

Two simultaneous ingests with identical `(event_type, auction_event_id, dedup_key)` serialise — exactly one row is persisted and the loser receives `ERR_DUPLICATE_BILLING_EVENT` (HTTP 409). The unique constraint is on that triple; first-writer-wins.

### 3.7. Conversion Attribution

A `ConversionEvent` is ingested by a `MeasurementPartner` or `ExchangeService` with a `source`, a `user_id` (the stitched cross-device end-user identifier), an `advertiser_id`, a `conversion_type` (an advertiser-defined event name such as `PURCHASE` or `SIGNUP`), and optional `value_cents` (defaulting to 0), `attribution_window_days` (defaulting to 7), and `attribution_model` (defaulting to `LAST_CLICK`). The `attribution_window_days` must be in the closed range from 1 to 90 inclusive; outside that range the request is rejected with `ERR_INVALID_ATTRIBUTION_WINDOW`. The conversion starts in `attribution_status` `PENDING` with `attributed_touchpoints` empty.

Attribution then runs — automatically on ingest, or explicitly on demand. The window is the set of `BillingEvent` rows whose `status` is `FINALIZED`, whose `event_type` is `CLICK` or `IMPRESSION`, whose `user_id` (joined through the originating auction) matches the conversion's stitched `user_id`, whose `advertiser_id` matches the conversion's `advertiser_id`, and whose `created_at` falls in the inclusive range from the conversion's `created_at` minus `attribution_window_days` days back to the conversion's `created_at`. A view-through restriction applies: `IMPRESSION` touchpoints receive credit only when no `CLICK` touchpoint exists in the same window. If the window is empty after this filter, the conversion's `attribution_status` becomes `UNATTRIBUTED` and `attributed_touchpoints` remains empty — this is a valid attribution result, not an error.

When at least one eligible touchpoint exists, the system sorts them by `created_at` ascending with `BillingEvent.id` ascending as the tie-break, then applies the chosen `attribution_model` to allocate credit. Under `LAST_CLICK`, the most recent `CLICK` touchpoint receives 100 percent of the credit; if no `CLICK` exists, the most recent `IMPRESSION` receives 100 percent. Under `POSITION_BASED`, the first touchpoint receives 40 percent, the last touchpoint receives 40 percent, and the remaining 20 percent is distributed equally among the middle touchpoints; when only one touchpoint exists it receives 100 percent, and when exactly two exist they each receive 50 percent. Under `DATA_DRIVEN`, the system computes for each position `i` from 1 (the earliest) to `N` (the latest) an inverse-recency weight: the raw weight for position `i` is one divided by `(N - i + 1)`, the per-position fraction is that raw weight divided by the sum of all raw weights, and that fraction is truncated to four decimal places (multiply by ten thousand, take the floor, divide by ten thousand). Once fractions are fixed, the integer-cent credit for each touchpoint is computed against the conversion's `value_cents`; the rounding order is fixed — fractions are allocated first to four decimal places, then integer cents are assigned, and any rounding remainder goes to the **last** touchpoint. The result, an ordered list of `(billing_event_id, credit_fraction)` pairs, is written to `attributed_touchpoints` and `attribution_status` is set to `ATTRIBUTED`. The three models all consume the same set of touchpoints but produce three different distributions; `LAST_CLICK` collapses to the most recent click, `POSITION_BASED` weights endpoints, and `DATA_DRIVEN` weights by recency over the whole sequence. The aggregated attribution report endpoint surfaces these results sliced by campaign and model for an advertiser, accepting optional `from`, `to`, and `attribution_model` filters.

### 3.8. Wallet Ledger, Recharges, Refunds, and Adjustments

Wallet operations are the exclusive domain of `FinanceOfficer` (with `PlatformAdmin` also permitted on creation and reversal). A wallet transaction is created with a `tx_type`, a signed `amount_cents` (positive for inflows like `RECHARGE` and `REFUND`, negative for outflows like `CONSUMPTION` and debit `ADJUSTMENT`), an `idempotency_key` unique per combination of `advertiser_id` and `tx_type`, an optional `reference_event_id` (the `BillingEvent.id` for a `CONSUMPTION` or the payment-provider id for a `RECHARGE`), and an optional `note` (required when `tx_type` is `ADJUSTMENT`).

A `RECHARGE`, `REFUND`, or `ADJUSTMENT` auto-settles synchronously: the transaction enters `PENDING` and immediately advances to `SETTLED`, the advertiser's `balance_cents` is adjusted by the signed `amount_cents`, `balance_state` is recomputed, and an `AuditLog` entry with `action` `BALANCE_ADJUSTMENT` is recorded for `ADJUSTMENT` and `REFUND` (and `action` `REFUND` for the dedicated refund path). An `INVOICE_SETTLEMENT` follows the same auto-settle path. A `CONSUMPTION` transaction created by the billing-event finalisation pipeline also auto-settles. The `PENDING → FAILED` transition exists for operator use when a payment provider declines a recharge.

Two safety rails protect the wallet. The refund-floor protection applies to a `REFUND` transaction or to any reversal of a settled wallet transaction: the resulting `balance_cents` MUST NOT drop below the negative of `credit_line_cents`, expressed as `balance_cents + amount_cents >= -credit_line_cents`. A violation is rejected with `ERR_REFUND_WOULD_BREACH_CREDIT_FLOOR` (HTTP 409). The adjustment-balance check applies to a debit `ADJUSTMENT` (a negative `amount_cents`): the same predicate must hold, but the rejection is `ERR_INSUFFICIENT_BALANCE` (HTTP 402). A re-submitted transaction with the same `(advertiser_id, tx_type, idempotency_key)` triple as an existing one is rejected with `ERR_IDEMPOTENCY_CONFLICT` (HTTP 409); the balance is only credited once. A reversal of an already-settled wallet transaction by a `FinanceOfficer` requires a non-empty `note`, applies the inverse amount to the balance, recomputes `balance_state`, sets the transaction's `status` to `REVERSED`, and writes an `AuditLog` entry; the forward-plus-reverse pair leaves `balance_cents` unchanged in net.

A consumption statement endpoint summarises wallet activity for a date range, accepting optional `from` and `to` query parameters; the list endpoint accepts optional `tx_type` and `status` filters. The audit-logs endpoint accepts optional `actor_user_id`, `action`, `target_entity_type`, `target_entity_id`, `from`, and `to` filters, while the billing-events list accepts optional `advertiser_id`, `campaign_id`, `status`, `from`, and `to` filters. The advertiser list endpoint accepts optional `account_type`, `parent_account_id`, and `status` filters; the campaigns list accepts optional `status`; the ad-groups list accepts optional `status`; the creatives list accepts optional `review_status`.

### 3.9. Balance Posture and Spend Aggregation

The advertiser's `balance_cents` is at all times the sum of `amount_cents` over every `WalletTransaction` belonging to the advertiser whose `status` is `SETTLED`. The advertiser's `consumed_cents` is the negative of the sum of `amount_cents` over every `CONSUMPTION` `WalletTransaction` belonging to the advertiser whose `status` is `SETTLED` — that is, the gross sum of all charges applied to the account, regardless of subsequent refunds. The window for both is from the beginning of time up to and including the current logical clock instant; sums are commutative so no tie-break is required.

The advertiser's `balance_state` is derived from `balance_cents` and `low_balance_threshold_cents`. If `balance_cents` is at most 0, `balance_state` is `ZERO_BALANCE`. If `balance_cents` is strictly greater than 0 and at most `low_balance_threshold_cents`, `balance_state` is `LOW_BALANCE`. Otherwise — strictly greater than `low_balance_threshold_cents` — `balance_state` is `HEALTHY`. When the system crosses from `HEALTHY` into `LOW_BALANCE`, it emits a low-balance alert (recorded in `AuditLog` with `action` of `BALANCE_ADJUSTMENT` and a note of `low_balance_alert`). When the system crosses into `ZERO_BALANCE`, every `RUNNING` `Campaign` belonging to the advertiser is paused, and so is every `RUNNING` `AdGroup` under those campaigns — this is the pause-on-zero protection. Subsequent inflows that lift the balance back above the threshold (or back above zero into the low band) transition `balance_state` back along the natural axis; campaigns and ad-groups do not auto-resume.

Per-campaign spend is similarly derived. `Campaign.lifetime_spent_cents` is the sum of `cost_cents` over every `BillingEvent` whose `campaign_id` matches and whose `status` is `FINALIZED`; rows in `REVERSED` subtract their original `cost_cents`. `Campaign.today_spent_cents` applies the same sum but restricted to events whose `finalized_at` is at or after the start of the current UTC day (inclusive) and strictly before the next UTC midnight (exclusive). A campaign reaches `BUDGET_EXHAUSTED` when `lifetime_spent_cents` is greater than or equal to `lifetime_budget_cents` (when set) or when `today_spent_cents` is greater than or equal to `daily_budget_cents`; when this happens, every `RUNNING` `AdGroup` under the campaign also moves to `BUDGET_EXHAUSTED`. A campaign returns from `BUDGET_EXHAUSTED` to `ACTIVE` automatically when the logical clock crosses into a new UTC day (so that `today_spent_cents` resets) and the lifetime budget — if set — has not been breached; ad-groups that were `BUDGET_EXHAUSTED` via this campaign also return to `RUNNING` automatically.

A platform admin advances the logical clock through a test-driving capability that supplies a number of `seconds` to advance. When the advance crosses a UTC midnight, the system triggers the budget-exhausted day-rollover transitions, recomputes per-campaign `today_spent_cents`, and emits any cascade-eligible state changes.

### 3.10. Risk Score

A risk score endpoint returns a derived reputation score for an advertiser, accepting an optional `mode` query parameter (one of `chronic` or `acute`; defaulting to `chronic`). The score is computed over a rolling window — 30 days in `chronic` mode, 24 hours in `acute` mode — by combining two rates and weighting them. The invalid-traffic rate is the count of `BillingEvent` rows for the advertiser whose `status` is either `INVALID_TRAFFIC` or `REVERSED` in the window, divided by the greater of 1 and the total count of `BillingEvent` rows for the advertiser in the window. The reject rate is the count of `Creative` rows for the advertiser whose `review_status` is `REJECTED` and were created in the window, divided by the greater of 1 and the total count of `Creative` rows created in the window. The raw score is the invalid-traffic rate times 0.6 plus the reject rate times 0.4; the published risk score is that raw score multiplied by 100, rounded half-up to the nearest integer, and capped at 100. The same advertiser computed in `chronic` and in `acute` mode generally returns two different integer scores because the windows differ; the answer is always an integer between 0 and 100 inclusive.

## 4. Endpoint Definitions

This section enumerates every endpoint by Method, Path, Description, and authorised role(s). Creation endpoints return HTTP 201 on success; non-creation mutations and reads return HTTP 200. Request and response shapes are not enumerated here — they follow from the workflows in §3 and the field semantics in §2.4–2.9.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/advance | Advance the deterministic test clock by N seconds, triggering day-rollover transitions where applicable | PlatformAdmin |
| POST | /advertisers | Create advertiser (MCC, sub-account, or independent) | PlatformAdmin |
| GET | /advertisers | List advertisers | PlatformAdmin |
| GET | /advertisers/{advertiserId} | Get advertiser | PlatformAdmin, AccountOwner, CampaignManager, FinanceOfficer, CreativeReviewer |
| PUT | /advertisers/{advertiserId} | Update advertiser settings (credit line, low-balance threshold, tax rate) | PlatformAdmin |
| POST | /advertisers/{advertiserId}/suspend | Suspend advertiser | PlatformAdmin |
| POST | /advertisers/{advertiserId}/reinstate | Reinstate suspended advertiser | PlatformAdmin |
| POST | /advertisers/{advertiserId}/close | Close advertiser permanently | PlatformAdmin |
| POST | /advertisers/{advertiserId}/qualifications | Upload qualification document | AccountOwner, PlatformAdmin |
| POST | /advertisers/{advertiserId}/qualifications/{docId}/review | Reviewer decides qualification document | PlatformAdmin |
| POST | /advertisers/{advertiserId}/users | Add user with role to advertiser account | PlatformAdmin, AccountOwner |
| GET | /advertisers/{advertiserId}/users | List account users | PlatformAdmin, AccountOwner, CampaignManager, FinanceOfficer |
| PATCH | /advertisers/{advertiserId}/users/{userId} | Change role or disable user | PlatformAdmin, AccountOwner |
| POST | /advertisers/{advertiserId}/campaigns | Create campaign | CampaignManager, AccountOwner |
| GET | /advertisers/{advertiserId}/campaigns | List campaigns | PlatformAdmin, AccountOwner, CampaignManager, FinanceOfficer |
| PUT | /advertisers/{advertiserId}/campaigns/{campaignId} | Update campaign | CampaignManager, AccountOwner |
| POST | /advertisers/{advertiserId}/campaigns/{campaignId}/activate | Activate campaign (DRAFT → ACTIVE or PAUSED → ACTIVE) | CampaignManager, AccountOwner |
| POST | /advertisers/{advertiserId}/campaigns/{campaignId}/pause | Pause campaign | CampaignManager, AccountOwner |
| POST | /advertisers/{advertiserId}/campaigns/{campaignId}/end | End campaign permanently | CampaignManager, AccountOwner |
| POST | /advertisers/{advertiserId}/campaigns/{campaignId}/ad-groups | Create ad-group | CampaignManager, AccountOwner |
| GET | /advertisers/{advertiserId}/campaigns/{campaignId}/ad-groups | List ad-groups in campaign | PlatformAdmin, AccountOwner, CampaignManager |
| PUT | /advertisers/{advertiserId}/campaigns/{campaignId}/ad-groups/{adGroupId} | Update ad-group | CampaignManager, AccountOwner |
| POST | /advertisers/{advertiserId}/campaigns/{campaignId}/ad-groups/{adGroupId}/activate | Activate ad-group (READY/PAUSED → RUNNING) | CampaignManager, AccountOwner |
| POST | /advertisers/{advertiserId}/campaigns/{campaignId}/ad-groups/{adGroupId}/pause | Pause ad-group | CampaignManager, AccountOwner |
| POST | /advertisers/{advertiserId}/campaigns/{campaignId}/ad-groups/{adGroupId}/archive | Archive ad-group | CampaignManager, AccountOwner |
| POST | /advertisers/{advertiserId}/campaigns/{campaignId}/ad-groups/{adGroupId}/creatives | Upload creative asset | CampaignManager, AccountOwner |
| GET | /advertisers/{advertiserId}/campaigns/{campaignId}/ad-groups/{adGroupId}/creatives | List creatives | PlatformAdmin, AccountOwner, CampaignManager, CreativeReviewer |
| POST | /creatives/{creativeId}/prescreen | Record pre-screen score and transition creative | PlatformAdmin |
| POST | /creatives/{creativeId}/human-review | Human reviewer decision on creative | CreativeReviewer |
| POST | /creatives/{creativeId}/appeal | Advertiser files appeal on rejected creative | CampaignManager, AccountOwner |
| POST | /creatives/{creativeId}/appeal/start-review | Reviewer accepts appeal for review | CreativeReviewer |
| POST | /creatives/{creativeId}/appeal/decide | Reviewer decides appeal | CreativeReviewer |
| POST | /creatives/{creativeId}/archive | Archive creative | CampaignManager, AccountOwner |
| GET | /creatives/{creativeId}/review-decisions | List review decisions for a creative (audit trail) | PlatformAdmin, AccountOwner, CreativeReviewer |
| POST | /auctions | Run an auction over candidate ad-groups for a single impression opportunity | ExchangeService, PlatformAdmin |
| GET | /auctions/{auctionId} | Get auction event | PlatformAdmin, ExchangeService |
| POST | /billing-events | Ingest impression / click / conversion event for billing | ExchangeService, MeasurementPartner |
| POST | /billing-events/{eventId}/reverse | Reverse a finalised billing event (late IVT) | AntiFraudService, PlatformAdmin |
| GET | /billing-events | List billing events | PlatformAdmin, AccountOwner, FinanceOfficer |
| POST | /conversions | Ingest a conversion event | MeasurementPartner, ExchangeService |
| POST | /conversions/{conversionId}/attribute | Run attribution algorithm | MeasurementPartner, PlatformAdmin |
| GET | /advertisers/{advertiserId}/reports/attribution | Attribution report aggregated by campaign and model | PlatformAdmin, AccountOwner, CampaignManager |
| POST | /advertisers/{advertiserId}/wallet/transactions | Create wallet transaction (recharge, refund, adjustment, invoice settlement) | FinanceOfficer, PlatformAdmin |
| GET | /advertisers/{advertiserId}/wallet/transactions | List wallet transactions | PlatformAdmin, AccountOwner, FinanceOfficer |
| POST | /advertisers/{advertiserId}/wallet/transactions/{txId}/reverse | Reverse a settled wallet transaction (compensating action) | FinanceOfficer, PlatformAdmin |
| GET | /advertisers/{advertiserId}/wallet/statement | Issue consumption statement for a date range | PlatformAdmin, AccountOwner, FinanceOfficer |
| GET | /advertisers/{advertiserId}/risk-score | Get advertiser risk score (chronic by default; mode=acute for 24h window) | PlatformAdmin, AntiFraudService |
| GET | /audit-logs | List audit-log entries | PlatformAdmin |

## 5. Error Code Catalogue

The following table enumerates every machine-readable `error_id` and its HTTP status code. The condition under which each fires is described in the prose of §2 and §3 — this table deliberately omits trigger conditions to avoid duplication.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_USER_CONTEXT | 401 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_SEGREGATION_OF_DUTIES_VIOLATION | 403 |
| ERR_APPEAL_SAME_REVIEWER | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_FREQUENCY_CAP | 400 |
| ERR_EMPTY_AUCTION_POOL | 400 |
| ERR_INVALID_ATTRIBUTION_WINDOW | 400 |
| ERR_INVALID_CAMPAIGN_DATES | 400 |
| ERR_ADVERTISER_NOT_FOUND | 404 |
| ERR_CAMPAIGN_NOT_FOUND | 404 |
| ERR_AD_GROUP_NOT_FOUND | 404 |
| ERR_CREATIVE_NOT_FOUND | 404 |
| ERR_QUALIFICATION_DOC_NOT_FOUND | 404 |
| ERR_BILLING_EVENT_NOT_FOUND | 404 |
| ERR_CONVERSION_NOT_FOUND | 404 |
| ERR_WALLET_TX_NOT_FOUND | 404 |
| ERR_AUDIENCE_NOT_FOUND | 422 |
| ERR_ADVERTISER_SUSPENDED | 409 |
| ERR_ADVERTISER_CLOSED | 409 |
| ERR_ADVERTISER_NOT_ACTIVE | 409 |
| ERR_INVALID_CAMPAIGN_STATE | 409 |
| ERR_INVALID_AD_GROUP_STATE | 409 |
| ERR_INVALID_CREATIVE_STATE | 409 |
| ERR_REVIEW_ALREADY_DECIDED | 409 |
| ERR_APPEAL_ALREADY_FILED | 409 |
| ERR_INVALID_BILLING_EVENT_STATE | 409 |
| ERR_DUPLICATE_BILLING_EVENT | 409 |
| ERR_QUALIFICATION_REQUIRED | 422 |
| ERR_DISCLAIMER_REQUIRED | 422 |
| ERR_INVALID_BUDGET | 422 |
| ERR_INVALID_CREDIT_LINE | 422 |
| ERR_ZERO_BALANCE | 402 |
| ERR_INSUFFICIENT_BALANCE | 402 |
| ERR_REFUND_WOULD_BREACH_CREDIT_FLOOR | 409 |
| ERR_IDEMPOTENCY_CONFLICT | 409 |
| ERR_CANNOT_CLOSE_WITH_ACTIVE_CAMPAIGNS | 409 |
