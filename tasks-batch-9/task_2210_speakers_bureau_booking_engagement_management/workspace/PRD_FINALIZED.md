# Speakers Bureau Engagements API — Product Requirements Document

## 1. Introduction

A professional speakers bureau sits between two parties who both believe they could do the deal without it. On one side is a roster of speakers with topic specialisms, fee expectations and travel requirements; on the other, client organisations with a date, an audience and a budget. The bureau's revenue is a commission on the fee it brokers, and that revenue is fragile: a quotation that expires unanswered, a speaker who double-books a Tuesday, an exclusivity promise nobody checked, or a client who quietly rebooks the same speaker directly next quarter all destroy margin that was never recorded anywhere. Today that entire chain lives in spreadsheets, e-mail threads and a shared calendar, and nobody can answer "how many days of this speaker's calendar are we holding right now?" without opening four tools.

This document specifies the API for a system that carries an engagement from an inbound inquiry through qualification, quotation, contracting, logistics, delivery, collection and speaker payout, and then feeds the outcome back into roster performance. The design goal is that every commercially consequential fact — the commission rate the deal was written at, the cancellation ladder the client agreed to, the exact window during which a competitor in the same industry may not book the same speaker — is pinned at the moment it is agreed rather than re-derived later from whatever the roster happens to look like. A second goal is arithmetic reproducibility: the same engagement, replayed with the same inputs against the same logical clock, must produce the same invoice to the cent and the same remittance to the cent.

Two structural consequences follow, and they shape most of what appears below. First, an engagement advances along two independent tracks — a booking track that records what the speaker and client agreed to do, and a settlement track that records who has paid whom — and neither track waits for the other. Second, several derived quantities on the roster and on the client account are **conserved**: they are maintained incrementally by the events that move them, and any operation that fails to compensate its own effect on reversal leaves the ledger permanently wrong. Implementers should treat the compensation clauses in §3 as being as normative as the happy paths.

## 2. Global Specifications & System-Wide Principles

Every path in this API is mounted at the top level; there is no shared prefix. Requests and responses are JSON.

### 2.1. Actors and Role-Based Access Control

Every request except the logical-clock capability described in §2.5 must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. If either header is absent, or if `X-User-Role` is not exactly one of `BureauAdmin`, `BookingAgent`, `Speaker` or `Client`, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is well-formed but is not among the roles listed for the target endpoint in §4, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The four roles differ in how `X-User-ID` is interpreted, and that difference is the whole basis of ownership enforcement:

- When `X-User-Role` is `Speaker`, `X-User-ID` is the `id` of the acting `Speaker` row. Ownership checks on any resource that references a `Speaker` compare the resource's speaker foreign-key field to `X-User-ID`: directly for an engagement, and through the engagement for a contract or a travel expense.
- When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `Client` row. Ownership checks compare the client reachable from the target resource to `X-User-ID`: `client_id` on an inquiry, the inquiry's client for a proposal or an engagement, the engagement's inquiry's client for a contract, and `client_id` on an invoice.
- When `X-User-Role` is `BookingAgent`, `X-User-ID` is an opaque deal-desk operator identifier that is not tied to any persisted entity. The server records it — as `owning_agent_user_id` on an `Inquiry` at qualification, as `created_by_agent_user_id` on a `Proposal` at creation, and as `owning_agent_user_id` copied onto the resulting `Engagement` — but never compares it to any entity's `id`. A `BookingAgent` acting on an engagement, a proposal or a travel expense must be the agent recorded in `owning_agent_user_id` for the engagement or for the proposal's inquiry.
- When `X-User-Role` is `BureauAdmin`, `X-User-ID` is likewise an opaque back-office operator identifier not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`, and `BureauAdmin` is never subject to the ownership check.

A caller who passes authentication and authorisation but fails the ownership test above is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). The ownership rule covers every `Client`-, `Speaker`- and `BookingAgent`-facing action endpoint on `Inquiry`, `Proposal`, `Engagement`, `Contract`, `TravelExpense` and `Invoice` resources, with exactly one deliberate exception: the commission-adjustment operation on an engagement is a four-eyes control, so ownership is not required there — instead the owner is specifically *barred*, and an attempt by the engagement's own `owning_agent_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). A commission adjustment must therefore come from a different `BookingAgent` user id, or from a `BureauAdmin`.

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

### 2.3. Pagination and Collection Filters

List endpoints are paginated through two query parameters. `limit` caps the number of rows returned; when omitted it defaults to 10, its minimum accepted value is 1 and its maximum accepted value is 100. `offset` is the number of rows to skip and defaults to 0. Unless a specific endpoint says otherwise, list results are ordered by `created_at` ascending. Every list response carries `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope.

Beyond pagination, each collection accepts a small set of equality filters, and callers may combine them freely:

- Roster listings accept `topic` (matching a single taxonomy code inside a speaker's topic list), `roster_status` and `roster_tier`.
- Client listings accept `industry_code` and `credit_status`.
- Calendar-hold listings accept `speaker_id`, `engagement_id`, `kind` and `status`.
- Inquiry listings accept `client_id`, `owning_agent_user_id`, `status` and `required_topic`.
- Proposal listings accept `inquiry_id`, `status` and `round_no`; option listings accept `proposal_id`, `speaker_id` and `status`.
- Engagement listings accept `inquiry_id`, `speaker_id`, `selected_option_id`, and independently either state dimension via `booking_status` and `settlement_status`.
- Contract listings accept `engagement_id` and `status`; travel-expense listings accept `engagement_id` and `status`; feedback listings accept `engagement_id`.
- Invoice listings accept `engagement_id`, `client_id`, `kind` and `status`; remittance listings accept `engagement_id`, `speaker_id` and `status`.
- Exclusivity-grant listings accept `speaker_id`, `beneficiary_client_id`, `source_engagement_id`, `industry_code` and `status`.
- Claim listings accept `client_id`, `speaker_id`, `source_engagement_id` and `status`.

### 2.4. Resource Identity, Audit Fields and Versioning

Every stored resource is addressable by an `id`, which is a server-minted UUID carrying no type prefix, and every resource records a `created_at` timestamp as an ISO 8601 UTC instant with three fractional digits. Almost all resources additionally carry `updated_at`, an ISO 8601 UTC instant refreshed on every mutation, and `version`, an integer that starts at 1 and increments by one on every mutation of that resource — including mutations the server performs on its own initiative as a cascade, and including rewrites of purely derived fields.

`Feedback` is the single exception. A feedback record is append-only: once filed it is never mutated, so it carries only `id` and `created_at`. Both `updated_at` and `version` are absent from a `Feedback` resource, and its `composite_score` is written once at creation and never recomputed even when the speaker's aggregate scores are.

### 2.5. The Logical Clock and Whole-Day Arithmetic

The server does not read wall-clock time. It keeps a **logical clock** whose value at startup is exactly `2026-08-01T00:00:00Z`, and which changes only when an operator advances it through `POST /_clock/set_current_utc`, supplying the new instant as `to_iso8601`. That endpoint answers with the new value as `current_utc` and modifies no stored row. It is also the one endpoint exempt from the header requirements of §2.1: it may be called without `X-User-ID` or `X-User-Role`, and when those headers are supplied any of the four roles is accepted.

Every temporal rule in this specification — lead-time screening, quotation expiry, the cancellation ladder, the non-circumvention protection window, exclusivity coverage, and the "has the event finished yet" gate on delivery and feedback — reads that logical clock. Wherever a rule counts **whole days** between two instants, the count is the number of seconds between them divided by 86400 and then floored to an integer. A floored count may be zero or negative, and where that happens the specification says explicitly what the sign means.

### 2.6. Money, Percentages and Rounding Discipline

All monetary amounts are integers denominated in cents; no field carries a fractional cent. Wherever a monetary result is produced by multiplying by a rate, the product is rounded **half up** to a whole number of cents. Percentage and rate fields — `commission_pct_snapshot`, `default_commission_pct`, `new_commission_pct`, `protection_factor` — are exact decimal numbers with two decimal places. Feedback-derived scores (`composite_score`, `rolling_score`, `lifetime_score`) are rounded half up to two decimal places.

Rounding **granularity** is normative, not incidental, and differs between calculations. The surcharge on an invoice is rounded once per line and the rounded parts are then summed; the commission on an engagement is rounded once on a single final product; the cancellation settlement rounds independently at three separate steps. §3 states which is which, and an implementation that rounds at a different point will produce different — and wrong — amounts for the same inputs.

### 2.7. Optimistic Concurrency on Inquiries and Engagements

Two write operations are guarded by optimistic concurrency control against the `version` of a *parent* resource. In both cases the version token is a required body field, not an optional one, and omitting it is a malformed request.

`POST /inquiries/{inquiryId}/proposals` requires `expected_inquiry_version`, carrying the `version` of the target `Inquiry` as the client last read it. If that value does not equal the inquiry's current `version`, the request is rejected with `ERR_STALE_INQUIRY_VERSION` (HTTP 412). The guard exists because opening a new proposal round legitimately supersedes every live quotation package on that inquiry, so a caller working from a stale view of the inquiry would silently discard a package it never saw. On success the inquiry's `version` advances by one.

`POST /engagements/{engagementId}/commission-adjustments` requires `expected_engagement_version`, carrying the `version` of the target `Engagement` as the caller last read it. If that value does not equal the engagement's current `version`, the request is rejected with `ERR_STALE_ENGAGEMENT_VERSION` (HTTP 412). The guard exists because each accepted adjustment overwrites `commission_pct_snapshot` and rewrites `provisional_commission_cents`, so an adjustment computed from a superseded snapshot would re-price the engagement from a rate that no longer applies. On success the engagement's `version` advances by one.

No other endpoint in this API accepts a version field, and no other endpoint performs a version check.

### 2.8. Cascade Discipline and Parallel State Dimensions

An `Engagement` carries two enumerated status fields that advance independently of one another. `booking_status` records the commercial booking and takes one of `OFFERED`, `CONFIRMED`, `CONTRACTED`, `DELIVERED`, `DECLINED_BY_SPEAKER`, `CANCELLED_BY_CLIENT` or `CANCELLED_BY_SPEAKER`, of which the last four are terminal. `settlement_status` records the money and takes one of `UNBILLED`, `INVOICED`, `PARTIALLY_COLLECTED`, `COLLECTED`, `REMITTED`, `WAIVED` or `WRITTEN_OFF`, of which the last three are terminal. The booking dimension does not move while the settlement dimension advances, and vice versa: an engagement whose `booking_status` is already the terminal `DELIVERED` will still travel from `INVOICED` through `PARTIALLY_COLLECTED` and `COLLECTED` to `REMITTED`.

Many operations in this system mutate more than one resource. Where §3 describes a secondary effect on a sibling or parent resource, that effect is mandatory and is performed inside the same request: each affected resource has its own `updated_at` refreshed and its own `version` incremented, and the response body is the resource named by the endpoint, not the cascade. Cascades that reverse an earlier effect must reverse it by the same amount that was originally applied, so that repeated forward-and-back movement leaves the derived totals of §2.9 exactly where they started.

### 2.9. Conserved Roster and Receivable Quantities

Several fields are running totals rather than inputs, and the invariant each one satisfies is stated here so that every operation in §3 can be checked against it.

On a `Speaker`: `held_days_count` equals the sum of `day_span` over that speaker's calendar holds whose `status` is `ACTIVE`; `engagements_delivered_count` equals the number of that speaker's engagements whose `booking_status` is `DELIVERED`; `lifetime_gross_fees_cents` equals the running sum of `quoted_fee_cents` plus `recording_fee_cents` over those delivered engagements; `pending_remittance_cents` equals the sum of `net_payable_cents` over that speaker's remittances whose `status` is `PENDING` or `APPROVED`; and `feedback_count` is the number of feedback rows filed across that speaker's engagements.

On a `Client`: `outstanding_balance_cents` equals the sum, over that client's invoices whose `status` is `ISSUED` or `PARTIALLY_PAID`, of `amount_due_cents` minus `amount_paid_cents`; `circumvention_strikes` equals the number of that client's claims whose `status` is `UPHELD` or `SETTLED`.

On a `Proposal`, `options_count` is the number of that proposal's options whose `status` is `OFFERED` or `SELECTED`, and `revision_count` is the number of client revision requests the package has absorbed. On an `Engagement`, `travel_reimbursable_cents` is the sum of `reimbursable_cents` over that engagement's travel expenses whose `status` is `APPROVED` or `REIMBURSED`, and `commission_adjustment_count` is the number of accepted commission adjustments. On an `Invoice`, `amount_paid_cents` is the cumulative amount collected across payment calls and begins at 0.

### 2.10. Path Resolution for Nested Routes

Where a path names more than one resource — an action segment hanging off a collection member, or a sub-collection such as the contracts or travel expenses of an engagement — identifiers are resolved strictly left to right, and the first identifier that does not resolve determines the error. A request naming a non-existent engagement and a well-formed but irrelevant body fails on the engagement, not on the body. Each resource type has its own not-found code: `ERR_SPEAKER_NOT_FOUND`, `ERR_CLIENT_NOT_FOUND`, `ERR_INQUIRY_NOT_FOUND`, `ERR_PROPOSAL_NOT_FOUND`, `ERR_OPTION_NOT_FOUND`, `ERR_ENGAGEMENT_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_HOLD_NOT_FOUND`, `ERR_TRAVEL_EXPENSE_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_REMITTANCE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_GRANT_NOT_FOUND` and `ERR_FEEDBACK_NOT_FOUND`, all HTTP 404. The same codes are reused when a foreign key supplied in a request body fails to resolve.

### 2.11. The Rejection Ladder

Because many operations are guarded by several rules at once, the order in which the server evaluates them is observable and therefore normative. When more than one rule would fail, the server reports the failure that comes first in the following ladder. Within the compliance, calendar, structural and money bands, the lettered order shown is likewise the evaluation order.

1. **Authentication.** `X-User-ID` and `X-User-Role` both present, and the role one of the four declared names — otherwise `ERR_UNAUTHENTICATED` (401). Applies to every endpoint except the logical-clock capability.
2. **Authorisation.** The supplied role appears in the target endpoint's role list — otherwise `ERR_UNAUTHORIZED` (403). Same scope as above.
3. **Path existence.** Every identifier in the path resolves, left to right, per §2.10 — otherwise the matching 404 code.
4. **Body well-formedness.** The body parses; every required input field is present; every enumerated value is a declared member of its enumeration; every amount field named with a cents suffix is an integer of at least 0; every instant field named with a UTC suffix is an ISO 8601 UTC instant; feedback scores are integers from 1 to 5 inclusive; `rank_no` is from 1 to 4 inclusive; `travel_days` is at least 1; and `new_commission_pct` and `amount_cents` are well-formed numbers. Any breach is `ERR_INVALID_REQUEST` (422). Applies to every creating and modifying request.
5. **Event window sanity.** On inquiry creation, `event_end_utc` must be strictly later than `event_start_utc` — otherwise `ERR_EVENT_WINDOW_INVALID` (422). Server-derived hold intervals and exclusivity windows are likewise never inverted.
6. **Body foreign keys.** `client_id` on inquiry creation; `speaker_id` on option creation and on manual hold creation; `option_id` on option selection; and `client_id`, `speaker_id` and `source_engagement_id` on claim creation must each resolve to a stored row — otherwise the corresponding 404 code from §2.10.
7. **Ownership.** The entity-backed and agent-ownership rules of §2.1 — otherwise `ERR_NOT_RESOURCE_OWNER` (403).
8. **Segregation of duties.** The engagement's own `owning_agent_user_id` may not post that engagement's commission adjustment — otherwise `ERR_SEGREGATION_OF_DUTIES` (403). This band guards the commission-adjustment operation only.
9. **Optimistic concurrency.** The version tokens of §2.7 — otherwise `ERR_STALE_INQUIRY_VERSION` or `ERR_STALE_ENGAGEMENT_VERSION` (412).
10. **Declared transition.** The target resource sits in a status from which the requested transition is declared: `status` on an inquiry for qualification and for opening a proposal round; `status` on a proposal for presentation, revision request, decline and selection; `booking_status` on an engagement for confirmation, speaker decline, contract drafting, delivery, cancellation, travel-expense submission and commission adjustment; `status` on a contract for sending and signing; `status` on a travel expense for approval and rejection; `status` on an invoice for payment and void; `status` on a remittance for payout; `status` on a claim for resolution; and `status` on an exclusivity grant for waiver. The codes are `ERR_INQUIRY_STATE_INVALID`, `ERR_PROPOSAL_STATE_INVALID`, `ERR_ENGAGEMENT_STATE_INVALID`, `ERR_CONTRACT_STATE_INVALID`, `ERR_TRAVEL_EXPENSE_STATE_INVALID`, `ERR_INVOICE_NOT_PAYABLE`, `ERR_REMITTANCE_NOT_APPROVED`, `ERR_CLAIM_NOT_OPEN` and `ERR_GRANT_NOT_ACTIVE`, all HTTP 409.
11. **Terminal and idempotency refinements**, evaluated only after the generic transition check above: cancelling or delivering an engagement whose `booking_status` is already one of the four terminal values is `ERR_ENGAGEMENT_ALREADY_TERMINAL`; signing a leg whose own signature stamp is already set is `ERR_PARTY_ALREADY_SIGNED`; filing a second feedback record for the same engagement is `ERR_FEEDBACK_ALREADY_SUBMITTED`. All HTTP 409, and this band guards engagement cancellation, engagement delivery, contract signing and feedback filing.
12. **Option membership.** The option named for selection must belong to the proposal in the path — otherwise `ERR_OPTION_NOT_IN_PROPOSAL` (409).
13. **Compliance and counterparty posture** (409 throughout), in this internal order: (a) the client's `credit_status` must not be `HOLD` for inquiry qualification, option selection and the client signature leg — `ERR_CLIENT_CREDIT_HOLD`; (b) the speaker's `roster_status` must be `ACTIVE` to be quoted on an option, to confirm an engagement and to sign the speaker leg — `ERR_SPEAKER_NOT_ACTIVE`; (c) the inquiry's `required_topic` must appear in the quoted speaker's `topics` when an option is created — `ERR_TOPIC_NOT_IN_ROSTER`; (d) the engagement's contract must be `EXECUTED` before a travel expense may be approved — `ERR_CONTRACT_NOT_EXECUTED`; (e) the speaker's `tax_form_status` must be `ON_FILE` before a remittance payout — `ERR_SPEAKER_TAX_FORM_MISSING`. This band guards inquiry qualification, option creation, option selection, engagement confirmation, contract signing, travel-expense approval and remittance payout. Compliance deliberately outranks the money band at position 18: the bureau may not quote a paused speaker even when the budget clears comfortably.
14. **Exclusivity screen**, on engagement confirmation only — `ERR_EXCLUSIVITY_CONFLICT` (409), as specified in §3.4.
15. **Calendar and clock** (409 throughout), in this internal order: (a) calendar conflict on confirmation or on a manual hold — `ERR_SPEAKER_CALENDAR_CONFLICT`; (b) insufficient lead time at qualification — `ERR_INSUFFICIENT_LEAD_TIME`; (c) an expired quotation when presenting, selecting or requesting a revision — `ERR_PROPOSAL_EXPIRED`; (d) the event window has not closed when delivering or filing feedback — `ERR_EVENT_NOT_ENDED`; (e) a directly booked event outside the protection window on claim creation — `ERR_OUTSIDE_PROTECTION_WINDOW`. This band guards engagement confirmation, manual hold creation, inquiry qualification, proposal presentation, option selection, revision requests, engagement delivery, feedback filing and claim creation.
16. **Structural constraints** (409 throughout), in this internal order: (a) presenting a package with no live options — `ERR_PROPOSAL_NO_OPTIONS`; (b) adding an option beyond the fourth — `ERR_OPTION_LIMIT_REACHED`; (c) quoting a speaker already quoted on a sibling option of the same proposal — `ERR_DUPLICATE_SPEAKER_OPTION`; (d) reusing a `rank_no` already taken on the same proposal — `ERR_DUPLICATE_RANK`; (e) requesting a revision beyond the second — `ERR_REVISION_LIMIT_REACHED`; (f) opening a duplicate claim — `ERR_DUPLICATE_CLAIM`. This band guards proposal presentation, option creation, revision requests and claim creation.
17. **Recording-rights consistency**, on contract drafting — `ERR_RECORDING_FEE_NOT_ALLOWED` or `ERR_RECORDING_FEE_REQUIRED` (both 422), as specified in §3.5.
18. **Money**, last within the business band, in this internal order: (a) the budget floor at qualification — `ERR_BUDGET_BELOW_FLOOR` (409); (b) the quoted fee against the speaker's range — `ERR_FEE_OUTSIDE_SPEAKER_RANGE` (409); (c) the quote against the inquiry's budget headroom — `ERR_QUOTE_EXCEEDS_BUDGET` (409); (d) a payment that is not positive or exceeds the invoice's remaining balance — `ERR_OVERPAYMENT` (409); (e) an out-of-range adjustment rate — `ERR_COMMISSION_PCT_OUT_OF_RANGE` (422); (f) a settlement amount outside the claim's assessed commission — `ERR_INVALID_REQUEST` (422). This band guards inquiry qualification, option creation, invoice payment, commission adjustment and claim resolution.

## 3. Business Logic & Workflows

### 3.1. Building the Roster and Keeping the Calendar

Roster onboarding is a `BureauAdmin` responsibility. Registering a speaker takes a `full_name` of between 1 and 120 characters, a `topics` array of between one and five distinct taxonomy codes drawn from `AI_STRATEGY`, `LEADERSHIP`, `HEALTHCARE_POLICY`, `CYBERSECURITY`, `FUTURE_OF_WORK` and `SALES_MOTIVATION`, a fee range expressed as `fee_floor_cents` (the lowest fee the speaker will accept, at least 0) and `fee_ceiling_cents` (the highest the bureau may quote, which must be greater than or equal to `fee_floor_cents`), and a contractual `travel_class` of `ECONOMY`, `PREMIUM` or `BUSINESS`. Two further inputs are optional: `travel_buffer_days`, a whole number of calendar days from 0 to 3 inclusive that defaults to 1 and pads both sides of any engagement this speaker takes, and `tax_form_status`, which is either `MISSING` or `ON_FILE` and defaults to `MISSING`.

Everything else on a new speaker is server-owned. `roster_status` starts at `ACTIVE` — the only value from which a speaker may be quoted, confirmed or signed, the alternatives being `PROBATION`, `PAUSED` and `RETIRED`. `roster_tier` starts at `BRONZE`, with `SILVER` and `GOLD` reachable only through the performance rules of §3.9, and `default_commission_pct` starts at the bronze rate of 0.25. The five running totals `engagements_delivered_count`, `lifetime_gross_fees_cents`, `held_days_count`, `pending_remittance_cents` and `feedback_count` all start at 0, while `rolling_score` and `lifetime_score` start null and stay null until the speaker's first feedback arrives.

Roster maintenance is the bureau's compliance lever. A `BureauAdmin` may revise `roster_status`, `tax_form_status`, `fee_floor_cents`, `fee_ceiling_cents`, `travel_class` and `travel_buffer_days` on an existing speaker; each such edit increments the speaker's `version` by one. `roster_tier` and `default_commission_pct` are never writable this way — they are derived, and the only thing that moves them is the tiering rule.

A speaker's calendar is a set of holds. A `BureauAdmin` or a `BookingAgent` may enter a manual blackout by naming the `speaker_id`, an inclusive `hold_start_utc`, an inclusive `hold_end_utc` and an optional free-text `reason`; the resulting hold has `kind` `BLACKOUT`, a null `engagement_id`, and `status` `ACTIVE`. The other flavour, `kind` `ENGAGEMENT`, is never entered directly — the server mints it when a speaker confirms a booking, as described in §3.4. Either way the server computes `day_span` as the number of distinct UTC calendar dates the closed interval from `hold_start_utc` to `hold_end_utc` touches, and adds that `day_span` to the speaker's `held_days_count`. A manual blackout that intersects an existing `ACTIVE` hold for the same speaker is refused with `ERR_SPEAKER_CALENDAR_CONFLICT`. A hold's `status` moves from `ACTIVE` to either `RELEASED` or `CONSUMED`, and neither of those values occupies the calendar; both departures are cascades from the engagement lifecycle and both decrement `held_days_count` by the hold's `day_span`.

### 3.2. Client Organisations, Inbound Inquiries and Qualification

Client organisations are registered by a `BureauAdmin` with an `org_name` of 1 to 160 characters, an `industry_code` drawn from `HEALTHCARE`, `FINANCE`, `TECHNOLOGY`, `EDUCATION` and `MANUFACTURING`, and a `primary_contact_email` used for proposals and billing. The industry code matters more than it looks: it is the dimension along which exclusivity is later granted and enforced. A new client's `credit_status` starts at `GOOD` — the alternatives being `WATCH` and the punitive `HOLD` — and both `outstanding_balance_cents` and `circumvention_strikes` start at 0. A `BureauAdmin` may subsequently revise `credit_status` and `primary_contact_email`, which increments the client's `version` by one; when the revision moves `credit_status` out of `HOLD` to either `GOOD` or `WATCH`, every inquiry of that client sitting in `BLOCKED` returns to `QUALIFIED` as a cascade.

An inbound enquiry is recorded by a `BookingAgent` or a `BureauAdmin` as an `Inquiry` naming the `client_id` that raised it, the `required_topic` the audience needs, the event window as `event_start_utc` and `event_end_utc`, the expected headcount as `audience_size` (at least 1), the client's stated speaking-fee budget as `budget_cents` (at least 0), and an `objective_tags` array of between one and four distinct codes drawn from `INSPIRE`, `STRATEGY`, `TRAINING` and `CELEBRATE`. An optional `is_virtual` flag defaults to false and, when true, has a decisive downstream consequence: travel is never reimbursable on a virtual engagement. `event_end_utc` must be strictly after `event_start_utc`, or the creation fails with `ERR_EVENT_WINDOW_INVALID`. A fresh inquiry has `status` `RECEIVED` and a null `owning_agent_user_id`; the full status enumeration is `RECEIVED`, `QUALIFIED`, `BLOCKED`, `PROPOSED`, `WON`, `LOST` and `DISQUALIFIED`, of which `WON`, `LOST` and `DISQUALIFIED` are terminal.

Qualification is where a deal desk operator takes ownership. A `BookingAgent` supplies an `outcome` of either `QUALIFY` or `DISQUALIFY` together with an optional `qualification_note`, and in **both** branches the server records the caller's `X-User-ID` as `owning_agent_user_id`, stores the `qualification_note`, and increments the inquiry's `version` by one. The two branches differ only in what they demand and where they land. `DISQUALIFY` demands only that the inquiry currently be `RECEIVED`, and moves it `RECEIVED → DISQUALIFIED`. `QUALIFY` also demands that the inquiry be `RECEIVED`, and adds three commercial screens before moving it `RECEIVED → QUALIFIED`: the client's `credit_status` must not be `HOLD`, or the attempt is refused with `ERR_CLIENT_CREDIT_HOLD`; there must be at least three full weeks of lead time, meaning the whole days from the logical clock to `event_start_utc` must be at least 21, or the attempt is refused with `ERR_INSUFFICIENT_LEAD_TIME`; and `budget_cents` must be at least the engagement floor of 2,500 dollars — that is, 250,000 cents — or the attempt is refused with `ERR_BUDGET_BELOW_FLOOR`.

One inquiry status is never reached by a client request at all. `QUALIFIED → BLOCKED` happens only as the fourth hop of the non-circumvention cascade in §3.9, and it is deliberately selective: when a client's credit posture collapses to `HOLD`, only that client's `QUALIFIED` inquiries are blocked, and rows sitting in `RECEIVED` or `PROPOSED` are left untouched. The reverse hop, `BLOCKED → QUALIFIED`, is the credit-posture edit described above.

### 3.3. Assembling and Negotiating the Quotation Package

A `Proposal` is one round of quotation against one inquiry. A `BookingAgent` opens a round on an inquiry that is either `QUALIFIED` or `PROPOSED`, supplying the concurrency token `expected_inquiry_version` described in §2.7 together with `valid_until_utc`, the instant at which the quotation stops being honourable. The new package records `inquiry_id`, records the opening agent's `X-User-ID` as `created_by_agent_user_id`, and starts in `DRAFT` with `round_no` 1, `revision_count` 0, `options_count` 0 and a null `presented_at_utc`. The proposal status enumeration is `DRAFT`, `PRESENTED`, `REVISION_REQUESTED`, `ACCEPTED`, `DECLINED`, `SUPERSEDED` and `CLOSED`, with `DECLINED`, `SUPERSEDED` and `CLOSED` terminal.

Opening a round is destructive to whatever came before it, which is precisely why it is version-guarded. Every existing proposal on the same inquiry sitting in `DRAFT`, `PRESENTED` or `REVISION_REQUESTED` moves to `SUPERSEDED`, and each superseded package takes its live options with it: every option of a superseded proposal in `OFFERED` moves to `WITHDRAWN`. All three supersession branches behave identically in that respect. The `PRESENTED → SUPERSEDED` branch carries one extra consequence: since the inquiry no longer has any presented quotation, it falls back `PROPOSED → QUALIFIED`. The `DRAFT → SUPERSEDED` and `REVISION_REQUESTED → SUPERSEDED` branches leave the inquiry's status alone, because a package in either of those states was never presented and so never pushed the inquiry to `PROPOSED`.

Options are the speaker choices inside a package. A `BookingAgent` adds one by naming the `proposal_id`, the `speaker_id` being offered, the `quoted_fee_cents` for that speaker, a `rank_no` from 1 to 4 giving the presentation order, and an optional `travel_allowance_cents` that defaults to 0 and becomes the contractual travel allowance floor carried into the engagement. A new option starts in `OFFERED`; the enumeration continues `SELECTED`, `REJECTED` and the terminal `WITHDRAWN`. Adding an option increments the parent package's `options_count` by one and its `version` by one. Options may only be added while the package is in `DRAFT` or `REVISION_REQUESTED`.

Adding an option is the densest validation point in the system. The offered speaker's `roster_status` must be `ACTIVE`, or the request is refused with `ERR_SPEAKER_NOT_ACTIVE`. The inquiry's `required_topic` must appear in that speaker's `topics`, or the request is refused with `ERR_TOPIC_NOT_IN_ROSTER`. Structurally, a package may carry at most four live options, so a fifth is refused with `ERR_OPTION_LIMIT_REACHED`; no sibling option on the same package may already quote the same `speaker_id`, or the request is refused with `ERR_DUPLICATE_SPEAKER_OPTION`; and no sibling may already use the same `rank_no`, or it is refused with `ERR_DUPLICATE_RANK`. Financially, `quoted_fee_cents` must fall inside the offered speaker's range — greater than or equal to `fee_floor_cents` and less than or equal to `fee_ceiling_cents` — or the request is refused with `ERR_FEE_OUTSIDE_SPEAKER_RANGE`. Finally the total exposure to the client, `quoted_fee_cents` plus `travel_allowance_cents`, may not exceed the inquiry's budget with a twenty-percent tolerance: the ceiling is `budget_cents` multiplied by 1.20 and rounded half up to a whole number of cents, and a quote above that ceiling is refused with `ERR_QUOTE_EXCEEDS_BUDGET`.

Presenting the package is what starts a negotiation round. A `BookingAgent` may present a package that is in `DRAFT` or in `REVISION_REQUESTED`, provided `options_count` is at least 1 — otherwise `ERR_PROPOSAL_NO_OPTIONS` — and provided the logical clock is strictly before `valid_until_utc`, an expired quotation being refused with `ERR_PROPOSAL_EXPIRED`. Presentation stamps `presented_at_utc` with the logical clock's current value and drives the inquiry `QUALIFIED → PROPOSED`. The two presentation branches differ in exactly one respect: `DRAFT → PRESENTED` leaves `round_no` at its current value, whereas `REVISION_REQUESTED → PRESENTED` increments `round_no` by one, so the number of times a package has gone out is always observable.

From `PRESENTED`, the client has three moves. Asking for a re-quote, with an optional `revision_note`, drives `PRESENTED → REVISION_REQUESTED`, increments `revision_count` by one, and walks the inquiry back `PROPOSED → QUALIFIED`; the loop is bounded on this leg and only on this leg, so a request made when `revision_count` already stands at 2 is refused with `ERR_REVISION_LIMIT_REACHED`. Declining the package outright, with an optional `decline_reason`, drives `PRESENTED → DECLINED`, moves every `OFFERED` option to `REJECTED`, and drives the inquiry `PROPOSED → LOST`. Both of those moves, like selection, require the logical clock to be strictly before `valid_until_utc`.

### 3.4. Selection, Engagement Creation and the Speaker's Answer

Selection is the moment a quotation becomes a booking. A `Client` names a single `option_id`, and the server checks that the package is `PRESENTED`, that the logical clock is strictly before `valid_until_utc`, that the named option belongs to the package in the path — a mismatch being `ERR_OPTION_NOT_IN_PROPOSAL` — that the option's own `status` is `OFFERED`, and that the client's `credit_status` is not `HOLD`. On success the named option moves `OFFERED → SELECTED` while every sibling in `OFFERED` moves `OFFERED → REJECTED`, the package moves `PRESENTED → ACCEPTED`, the inquiry moves `PROPOSED → WON`, and a new `Engagement` is minted.

The engagement is deliberately a snapshot rather than a set of pointers. It records `inquiry_id`, `speaker_id` and `selected_option_id` for traceability, copies `owning_agent_user_id` from the inquiry so that segregation of duties has an anchor, copies `event_start_utc`, `event_end_utc` and `is_virtual` from the inquiry, and copies `quoted_fee_cents` and `travel_allowance_cents` from the selected option. Its `booking_status` begins at `OFFERED` and its `settlement_status` at `UNBILLED`. The agreement-derived fields `recording_rights`, `recording_fee_cents` and `technical_rider_code` default to `NONE`, 0 and `STANDARD_AV` respectively and are overwritten from the contract at execution. `commission_pct_snapshot`, `provisional_commission_cents`, `final_commission_cents`, `retention_net_cents` and `retention_commission_cents` are all null on a fresh engagement — indeed they stay null for any engagement in `OFFERED`, `CONFIRMED`, `DECLINED_BY_SPEAKER` or either cancelled booking state, because none of those states has an executed agreement to price against. `travel_reimbursable_cents` starts at 0, `commission_adjustment_count` at 0, and `cancelled_by` and `cancellation_days_before` stay null until a cancellation actually occurs; `cancelled_by` admits `CLIENT`, `SPEAKER` and `BUREAU`.

The speaker now answers, and the two answers are mirror images of one another. **Confirmation** requires the engagement to be `OFFERED` and the speaker's `roster_status` to be `ACTIVE`. Before anything else the server performs a lazy expiry sweep: every exclusivity grant whose `status` is `ACTIVE` and whose `effective_to_utc` is at or before the logical clock is flipped to `EXPIRED`. Only then does the exclusivity screen run over the surviving `ACTIVE` grants: if any grant for this same `speaker_id`, carrying the same `industry_code` as this engagement's client, and whose `beneficiary_client_id` is a *different* client, covers this engagement's `event_start_utc` within the half-open window running from `effective_from_utc` inclusive to `effective_to_utc` exclusive, the confirmation is refused with `ERR_EXCLUSIVITY_CONFLICT`. Next comes the calendar: no `ACTIVE` hold for this speaker may intersect the buffered **closed** interval running from `event_start_utc` minus `travel_buffer_days` days to `event_end_utc` plus `travel_buffer_days` days, and an intersection is refused with `ERR_SPEAKER_CALENDAR_CONFLICT`. When all of that passes, the engagement moves `OFFERED → CONFIRMED`, the server mints a hold of `kind` `ENGAGEMENT` and `status` `ACTIVE` spanning exactly that buffered closed interval — so `hold_start_utc` is `event_start_utc` minus the buffer and `hold_end_utc` is `event_end_utc` plus the buffer — and the speaker's `held_days_count` grows by the new hold's `day_span`.

**Declining** requires only that the engagement be `OFFERED`, takes an optional `decline_reason`, and unwinds the selection so the client can choose again. The engagement moves `OFFERED → DECLINED_BY_SPEAKER`, which is terminal. The previously selected option moves `SELECTED → REJECTED`; every sibling option of that same package that had been swept to `REJECTED` at selection time returns to `OFFERED`; the package itself moves `ACCEPTED → PRESENTED`, which is the second cycle on that entity and is permitted only while the logical clock remains strictly before `valid_until_utc`; and the inquiry walks back `WON → PROPOSED`. No hold exists yet at this point, because a hold is only minted on confirmation.

An engagement's own hold leaves the calendar in exactly two ways, and both decrement `held_days_count` by the hold's `day_span`. Delivery consumes it, moving that hold `ACTIVE → CONSUMED`. Cancellation releases it, moving that hold `ACTIVE → RELEASED`. Manual blackout holds are never touched by either event.

### 3.5. Papering the Agreement: Two Legs, One Execution

Once a speaker has confirmed, a `BookingAgent` drafts the speaker agreement against that `CONFIRMED` engagement, recording `engagement_id` and four commercial choices. `cancellation_schedule_code` selects the retention ladder, either `STANDARD` or `STRICT`. `travel_policy_code` selects the reimbursement rule, either `POLICY_A` or `POLICY_B`. `recording_rights` grants `NONE`, `AUDIO_ONLY` or `FULL_BUY_OUT`. `exclusivity_days` is the length in days of the industry exclusivity window promised to the client and must be exactly one of 0, 30, 90 or 180, defaulting to 0. Two further inputs are optional: `recording_fee_cents`, the buy-out fee, defaulting to 0, and `technical_rider_code`, the on-site technical profile, one of `STANDARD_AV`, `STAGE_PLUS` or `BROADCAST`, defaulting to `STANDARD_AV`. Recording rights and recording fee must agree with each other: if `recording_rights` is `NONE` then `recording_fee_cents` must be absent or 0, and a positive fee is refused with `ERR_RECORDING_FEE_NOT_ALLOWED`; conversely if `recording_rights` is `AUDIO_ONLY` or `FULL_BUY_OUT` then `recording_fee_cents` must be strictly greater than 0, and an absent or zero fee is refused with `ERR_RECORDING_FEE_REQUIRED`. A drafted agreement starts in `DRAFT` with `speaker_signed_at_utc`, `client_signed_at_utc` and `executed_at_utc` all null; the status enumeration continues `SENT`, `PARTIALLY_SIGNED` and the two terminal values `EXECUTED` and `VOID`.

Sending the drafted agreement out for signature is a `BookingAgent` action that requires the agreement to be in `DRAFT` and the engagement to be `CONFIRMED`, and moves the agreement `DRAFT → SENT`.

Signature is a fork and join. Each party signs their own leg by supplying a `signature_name`, and the two legs are guarded differently and stamp different fields. The **speaker leg** is available to the acting `Speaker` while `speaker_signed_at_utc` is still null, is gated on the speaker's `roster_status` being `ACTIVE` — a paused speaker is refused with `ERR_SPEAKER_NOT_ACTIVE` — and stamps `speaker_signed_at_utc` with the logical clock. The **client leg** is available to the acting `Client` while `client_signed_at_utc` is still null, is gated on the client's `credit_status` not being `HOLD` — a held client is refused with `ERR_CLIENT_CREDIT_HOLD` — and stamps `client_signed_at_utc` with the logical clock. Whichever party signs first drives the agreement `SENT → PARTIALLY_SIGNED`. A party attempting to sign a leg whose own stamp is already set is refused with `ERR_PARTY_ALREADY_SIGNED`. At the join, the party who has not yet signed drives `PARTIALLY_SIGNED → EXECUTED`, and that second signature must still satisfy its own guard — the speaker's `roster_status` for the speaker leg, the client's `credit_status` for the client leg.

Execution is the single most consequential instant in the system, and it fans out. `executed_at_utc` is stamped with the logical clock alongside the missing signature field. The engagement moves `CONFIRMED → CONTRACTED`. The agreement's `recording_rights`, `recording_fee_cents` and `technical_rider_code` are copied onto the engagement. `commission_pct_snapshot` is pinned from the speaker's `default_commission_pct` **as it stands at this instant** and is never re-read from the speaker afterwards, so a later tier move does not re-price this engagement. `provisional_commission_cents` is then written as the provisional variant of the commission calculation: `quoted_fee_cents` multiplied by `commission_pct_snapshot`, that single product rounded half up to a whole number of cents. The provisional figure covers the fee line alone and deliberately excludes recording revenue, on the reasoning that a buy-out is not earned until the session is actually recorded; whenever `recording_fee_cents` is positive, the provisional figure therefore understates what the bureau will ultimately withhold. The quotation package that produced this engagement moves `ACCEPTED → CLOSED`. And when `exclusivity_days` is greater than 0, an `ExclusivityGrant` is created in `status` `ACTIVE`, recording `source_engagement_id` as this engagement, `speaker_id` as this speaker, `beneficiary_client_id` as this engagement's client, `industry_code` copied from that beneficiary client, `effective_from_utc` equal to the engagement's `event_end_utc`, and `effective_to_utc` equal to `effective_from_utc` plus `exclusivity_days` days — the window being inclusive at its start and **exclusive** at its end. When `exclusivity_days` is 0 no grant is created at all.

A grant restricts confirmations only while it is `ACTIVE`. It reaches `EXPIRED` either through the lazy sweep at confirmation time described in §3.4 or as a cascade when its source engagement is cancelled. A `BureauAdmin` may also deliberately release one, supplying an optional `waiver_reason`, which drives `ACTIVE → WAIVED` so the speaker can be confirmed for a competing client; waiving a grant that is already `EXPIRED` or `WAIVED` is refused with `ERR_GRANT_NOT_ACTIVE`.

An agreement that never reaches execution can be voided. When an engagement is cancelled, any agreement of that engagement sitting in `DRAFT`, `SENT` or `PARTIALLY_SIGNED` moves to `VOID` as a cascade; all three source states behave identically.

### 3.6. Travel Logistics and Reimbursement

Travel receipts may be filed by the acting `Speaker` or by the owning `BookingAgent` against an engagement whose `booking_status` is `CONFIRMED` or `CONTRACTED` — the receipt may arrive as soon as the booking is confirmed, even though the rule for paying it lives on the agreement. A submission carries `receipts_cents`, the total submitted receipts in cents, `travel_days`, the whole travel days claimed and at least 1, a `distance_band` of `LOCAL`, `REGIONAL`, `NATIONAL` or `INTERNATIONAL`, and an optional free-text `memo` describing the itinerary. It records `engagement_id`, starts in `SUBMITTED` with `reimbursable_cents` null, and can end in `APPROVED`, the terminal `REJECTED`, or the terminal `REIMBURSED`.

Rejection is a `BookingAgent` action on a `SUBMITTED` receipt, takes an optional `rejection_reason`, drives `SUBMITTED → REJECTED`, leaves `reimbursable_cents` null, and adds nothing whatever to the engagement's `travel_reimbursable_cents`. Approval is the same actor on the same source state but demands three further conditions: the engagement's `booking_status` must be `CONTRACTED`, the engagement's agreement must actually be `EXECUTED` — otherwise `ERR_CONTRACT_NOT_EXECUTED` — and the engagement's `settlement_status` must still be `UNBILLED`, since once billing has begun the travel line has already been struck. Approval drives `SUBMITTED → APPROVED`, writes `reimbursable_cents`, and increases the engagement's `travel_reimbursable_cents` by that amount.

The reimbursable amount is computed as follows, and the nesting of the comparisons is normative.

- If the engagement's `is_virtual` is true, `reimbursable_cents` is 0. No travel occurs for a virtual delivery, and no other input is even consulted.
- Otherwise, if the agreement's `travel_policy_code` is `POLICY_A`, the server first computes a schedule amount: the per-day rate for the receipt's `distance_band`, multiplied by the claimed `travel_days`, multiplied by the multiplier for the speaker's `travel_class`, with that single product rounded half up to a whole number of cents. The daily rates are 150 dollars for `LOCAL` (15,000 cents per travel day), 450 dollars for `REGIONAL` (45,000 cents), 900 dollars for `NATIONAL` (90,000 cents) and 1,800 dollars for `INTERNATIONAL` (180,000 cents); the class multipliers are 1.00 for `ECONOMY`, 1.25 for `PREMIUM` and 1.60 for `BUSINESS`. The ceiling is then the **greater** of the engagement's `travel_allowance_cents` and that rounded schedule amount, and `reimbursable_cents` is the **lesser** of `receipts_cents` and that ceiling. Under this policy the negotiated allowance therefore acts as a floor beneath the ceiling — a generous allowance is honoured even when the mileage schedule is stingy — while the receipts always cap the payout. Taking the greater of the allowance and the receipt-capped schedule instead would reimburse more than the receipts prove, and is wrong.
- Otherwise the agreement is on `POLICY_B`, a hard allowance cap: the ceiling is simply the engagement's `travel_allowance_cents`, and `reimbursable_cents` is the lesser of `receipts_cents` and that ceiling. The distance schedule and the travel class are not consulted at all.

Because each approval adds its own `reimbursable_cents` to the engagement's running `travel_reimbursable_cents`, several approved receipts on one engagement accumulate. Each is capped on its own terms; the cap is never re-applied to the accumulated total.

### 3.7. Delivery, Invoicing and Collection

Delivery is the `BookingAgent`'s closing act on the booking track and the opening act on the settlement track. It requires the engagement's `booking_status` to be `CONTRACTED`, the engagement's agreement to be `EXECUTED`, and the logical clock to be at or after the engagement's `event_end_utc`; an attempt before the window closes is refused with `ERR_EVENT_NOT_ENDED`. Delivery drives `CONTRACTED → DELIVERED` on the booking dimension and `UNBILLED → INVOICED` on the settlement dimension, and it triggers a chain of six consequences.

First, `final_commission_cents` is written as the final variant of the commission calculation: `quoted_fee_cents` **plus** `recording_fee_cents`, that sum multiplied by `commission_pct_snapshot`, and that single product rounded half up to a whole number of cents. Same engagement, same pinned rate, but a strictly larger result than the provisional figure whenever `recording_fee_cents` is positive; the difference — `recording_fee_cents` multiplied by `commission_pct_snapshot`, rounded half up — is exactly the extra amount the remittance withholds beyond the provisional figure.

Second, an `Invoice` is issued with `kind` `ENGAGEMENT_FEE` and `status` `ISSUED`, recording `engagement_id`, the payer as `client_id`, and `issued_at_utc` stamped with the logical clock. Its three lines come straight off the engagement: `fee_line_cents` is `quoted_fee_cents`, `recording_line_cents` is `recording_fee_cents`, and `travel_line_cents` is the engagement's `travel_reimbursable_cents` as it stands at issuance. The processing surcharge is then computed at a rate of 1.75 percent — that is, 0.0175 — and the **order of operations is normative**: the server multiplies each of the three lines by the surcharge rate separately, rounds each of those three products half up to a whole number of cents, and only then adds the three rounded parts together to obtain `surcharge_cents`. Summing the three lines first and rounding a single product would yield a different `surcharge_cents` for the same engagement whenever the discarded fractions of the individual lines re-combine across the half-cent boundary, and is wrong. `amount_due_cents` is then the sum of `fee_line_cents`, `recording_line_cents`, `travel_line_cents` and `surcharge_cents`; `amount_paid_cents` starts at 0. The surcharge is bureau revenue and is never remitted to the speaker. An invoice's `status` runs `ISSUED`, `PARTIALLY_PAID`, and then the terminal `PAID` or `VOID`.

Third, the client's `outstanding_balance_cents` grows by the new invoice's `amount_due_cents`.

Fourth, a `Remittance` is created in `status` `PENDING`, recording `engagement_id` and the payee as `speaker_id`, with `paid_at_utc` null. For a delivery, its `gross_fee_cents` is the commissionable base `quoted_fee_cents` plus `recording_fee_cents`; its `commission_cents` is the engagement's `final_commission_cents`; its `travel_passthrough_cents` is the engagement's `travel_reimbursable_cents`, which is passed straight through to the speaker and is never commissioned; and its `net_payable_cents` is `gross_fee_cents` minus `commission_cents` plus `travel_passthrough_cents`. The speaker's `pending_remittance_cents` grows by that `net_payable_cents`. The remittance status enumeration continues `APPROVED` and then the terminal `PAID` or `VOIDED`.

Fifth, the engagement's own calendar hold moves `ACTIVE → CONSUMED` and the speaker's `held_days_count` drops by that hold's `day_span`.

Sixth, and this is the four-hop roster cascade: the speaker's `engagements_delivered_count` rises by one and `lifetime_gross_fees_cents` rises by `quoted_fee_cents` plus `recording_fee_cents`; because the delivered count changed, the tiering rule of §3.9 re-runs and may move `roster_tier`; and because `roster_tier` may have moved, the speaker's `default_commission_pct` is rewritten to the rate implied by the new tier. Engagements already contracted keep their own `commission_pct_snapshot` untouched — only agreements executed after the change pick up the new rate.

Collection is a series of payments against an issued invoice, filed by the acting `Client` or by a `BureauAdmin` with an `amount_cents` and an optional `method`. The amount must be strictly greater than 0 and no greater than the invoice's remaining balance, that is `amount_due_cents` minus `amount_paid_cents`; anything else is refused with `ERR_OVERPAYMENT`. A payment against an invoice that is already `PAID` or `VOID` is refused with `ERR_INVOICE_NOT_PAYABLE`. Every accepted payment increases `amount_paid_cents` by `amount_cents` and decreases the client's `outstanding_balance_cents` by the same `amount_cents`. Where it lands depends on whether the payment settles the remainder. A payment strictly smaller than the remaining balance drives the invoice `ISSUED → PARTIALLY_PAID` and the engagement's settlement dimension `INVOICED → PARTIALLY_COLLECTED`. A payment exactly equal to the remaining balance drives the invoice to `PAID` — `ISSUED → PAID` when this single payment settles the whole invoice, or `PARTIALLY_PAID → PAID` when earlier partial payments had already landed — drives the settlement dimension to `COLLECTED` by the matching leg, `INVOICED → COLLECTED` in the first case and `PARTIALLY_COLLECTED → COLLECTED` in the second, and, as a cascade, moves that engagement's remittance `PENDING → APPROVED`. Approval of the payout is thus never a manual step: it is the arithmetic consequence of the invoice being fully collected.

A `BureauAdmin` may void an issued invoice, supplying an optional `void_reason`. Voiding is only available while the invoice is `ISSUED`; an invoice that is already `PARTIALLY_PAID`, `PAID` or `VOID` is refused with `ERR_INVOICE_NOT_PAYABLE`. The void drives the invoice `ISSUED → VOID`, decreases the client's `outstanding_balance_cents` by `amount_due_cents` minus `amount_paid_cents` so that the balance returns to exactly where it stood before issuance, drives the engagement's settlement dimension `INVOICED → WRITTEN_OFF`, and moves the engagement's remittance `PENDING → VOIDED` while decreasing the speaker's `pending_remittance_cents` by that remittance's `net_payable_cents`.

Paying the speaker is the last money movement. A `BureauAdmin` pays out a remittance whose `status` is `APPROVED`, supplying an optional `payment_reference`; a remittance in any other status is refused with `ERR_REMITTANCE_NOT_APPROVED`, and a payout attempted while the speaker's `tax_form_status` is `MISSING` is refused with `ERR_SPEAKER_TAX_FORM_MISSING`. The payout drives the remittance `APPROVED → PAID`, stamps `paid_at_utc` with the logical clock, decreases the speaker's `pending_remittance_cents` by `net_payable_cents`, drives the engagement's settlement dimension `COLLECTED → REMITTED`, and moves every travel expense of that engagement sitting in `APPROVED` to `REIMBURSED`.

### 3.8. Cancellation, Retention and Commission Re-Pricing

Cancellation is available while the engagement's `booking_status` is `CONFIRMED` or `CONTRACTED`, to the acting `Client`, to the acting `Speaker`, or to a `BureauAdmin` who must declare which side they act for by supplying `on_behalf_of`; an optional `cancellation_reason` may accompany any of them. An attempt against an engagement already in one of the four terminal booking states is refused with `ERR_ENGAGEMENT_ALREADY_TERMINAL`. In every branch the server records `cancelled_by` from the acting side — `CLIENT` or `SPEAKER`, taken from `on_behalf_of` when a `BureauAdmin` acts — and records `cancellation_days_before` as the whole days from the logical clock to `event_start_utc`, computed as the difference in seconds divided by 86400 and floored. In every branch the engagement's calendar hold moves `ACTIVE → RELEASED` and the speaker's `held_days_count` drops by that hold's `day_span`. Beyond that shared core, the four branches diverge, and the divergence is the whole commercial point of the cancellation clause.

A **client-side cancellation of a `CONFIRMED` engagement** — one where the agreement was never executed — moves the booking dimension `CONFIRMED → CANCELLED_BY_CLIENT`, voids any agreement sitting in `DRAFT`, `SENT` or `PARTIALLY_SIGNED`, and moves the settlement dimension `UNBILLED → WAIVED`. Nothing is billed, because with no executed agreement there is no retention clause to enforce.

A **client-side cancellation of a `CONTRACTED` engagement** moves the booking dimension `CONTRACTED → CANCELLED_BY_CLIENT` and runs the retention settlement in six pinned steps.

1. `cancellation_days_before` is the floored whole-day count described above.
2. A retention percentage is read off the ladder that the agreement's `cancellation_schedule_code` selected, and every band is inclusive at its lower bound. Under `STANDARD`: 30 or more days before the event retains nothing, 0.00; from 14 to 29 days inclusive retains 0.50; fewer than 14 days retains the whole fee, 1.00. Under `STRICT`: 60 or more days before the event still retains 0.25; from 21 to 59 days inclusive retains 0.75; fewer than 21 days retains 1.00.
3. The gross retention is `quoted_fee_cents` multiplied by that retention percentage, rounded half up to a whole number of cents.
4. A goodwill rebate percentage is keyed on the **gross** retention of step 3, not on any later figure: a gross retention of 5,000 dollars or more (500,000 cents or more) earns a rebate of 0.10; a gross retention from 2,000 dollars up to but not including 5,000 dollars (200,000 through 499,999 cents inclusive) earns 0.05; anything below 2,000 dollars (under 200,000 cents) earns nothing, 0.00. The rebate amount is the gross retention multiplied by that rebate percentage, rounded half up.
5. `retention_net_cents` is the gross retention minus the rebate amount.
6. `retention_commission_cents` is `retention_net_cents` multiplied by `commission_pct_snapshot`, rounded half up — the bureau commissions the **net** retention, never the gross.

The six steps are order-pinned: keying the rebate band on the net figure of step 5, or commissioning the gross figure of step 3, produces a different invoice and a different remittance from identical inputs. `recording_fee_cents` is never retained, on the reasoning that an unrecorded session earns no buy-out.

What happens next depends on whether anything is actually billable. When `retention_net_cents` plus the engagement's `travel_reimbursable_cents` is greater than 0, an `Invoice` is issued with `kind` `CANCELLATION_RETENTION` and `status` `ISSUED`, and its line composition differs from a fee invoice: `fee_line_cents` is `retention_net_cents`, `recording_line_cents` is always 0 on a retention invoice, and `travel_line_cents` is again the engagement's `travel_reimbursable_cents`. The same per-line surcharge treatment of §3.7 applies — each line multiplied by 0.0175 and rounded half up separately, the three rounded parts then summed into `surcharge_cents` — and `amount_due_cents` is again the sum of the three lines plus `surcharge_cents`. The settlement dimension moves `UNBILLED → INVOICED`, the client's `outstanding_balance_cents` grows by `amount_due_cents`, and a `Remittance` is created in `PENDING` whose `gross_fee_cents` is `retention_net_cents`, whose `commission_cents` is `retention_commission_cents`, whose `travel_passthrough_cents` is the engagement's `travel_reimbursable_cents`, and whose `net_payable_cents` is again `gross_fee_cents` minus `commission_cents` plus `travel_passthrough_cents`; the speaker's `pending_remittance_cents` grows accordingly. When instead `retention_net_cents` plus `travel_reimbursable_cents` comes out at exactly 0 — a full-waiver band with no approved travel — no invoice and no remittance are created at all and the settlement dimension moves `UNBILLED → WAIVED`. Either way, every exclusivity grant whose `source_engagement_id` is this engagement and whose `status` is `ACTIVE` moves to `EXPIRED`: a cancelled booking earns no exclusivity.

A **speaker-side cancellation** bills nothing regardless of how far the deal had progressed, and adds a roster consequence. From `CONFIRMED` the booking dimension moves `CONFIRMED → CANCELLED_BY_SPEAKER`; from `CONTRACTED` it moves `CONTRACTED → CANCELLED_BY_SPEAKER`. In both cases `cancelled_by` is `SPEAKER`, no retention is computed, the settlement dimension moves `UNBILLED → WAIVED`, and the speaker's `roster_status` moves `ACTIVE → PROBATION`, which immediately makes that speaker unquotable, unconfirmable and unable to sign until a `BureauAdmin` restores them. The two speaker-side branches differ only in their collateral: from `CONFIRMED`, an unexecuted agreement in `DRAFT`, `SENT` or `PARTIALLY_SIGNED` moves to `VOID`; from `CONTRACTED`, the agreement is already `EXECUTED` and instead every `ACTIVE` exclusivity grant sourced from this engagement moves to `EXPIRED`.

Finally, a contracted engagement's commission rate can be renegotiated, but only under four-eyes control. A commission adjustment may be posted by a `BookingAgent` or a `BureauAdmin` against an engagement whose `booking_status` is `CONTRACTED`, and it carries three required fields: the concurrency token `expected_engagement_version` of §2.7, the replacement rate `new_commission_pct`, and a `reason` recording why. The rate must lie between 0.10 and 0.35 inclusive, and a value outside that band is refused with `ERR_COMMISSION_PCT_OUT_OF_RANGE`. The agent who owns the engagement is specifically barred: an attempt by the caller whose `X-User-ID` equals the engagement's `owning_agent_user_id` is refused with `ERR_SEGREGATION_OF_DUTIES`, and this is the one operation in the system where the owning agent has *less* authority than a stranger. An accepted adjustment overwrites `commission_pct_snapshot` with `new_commission_pct`, rewrites `provisional_commission_cents` using the provisional formula at the new rate — `quoted_fee_cents` multiplied by the new snapshot, rounded half up — and increments `commission_adjustment_count` by one.

### 3.9. Feedback, Roster Performance and Non-Circumvention Protection

Only the booking client may rate a delivered engagement, and only once. Filing feedback requires the engagement's `booking_status` to be `DELIVERED` and the logical clock to be at or after `event_end_utc` — otherwise `ERR_EVENT_NOT_ENDED` — and a second attempt on the same engagement is refused with `ERR_FEEDBACK_ALREADY_SUBMITTED`. The submission carries `content_score` and `logistics_score`, each an integer from 1 to 5 inclusive, plus an optional `rebook_intent` boolean recording whether the client would book this speaker again and an optional free-text `comment`. The record stores `engagement_id` and a `composite_score` computed once and never revisited: `content_score` weighted at 0.6 plus `logistics_score` weighted at 0.4, rounded half up to two decimal places.

Filing feedback then re-scores the speaker. The candidate set is every feedback record reachable from that speaker's engagements, ordered by the record's `created_at` descending and, as a tie-break, by its engagement's `event_start_utc` descending. Where two records share both keys, both remain in the set and their relative weight positions follow that same descending ordering; a record's `id` is never a decision input. Two aggregate figures are recomputed and stored, and they read exactly the same rows, differing only in how those rows are weighted:

- `lifetime_score` is the equal-weight arithmetic mean of `composite_score` across **all** candidates, rounded half up to two decimal places. There is no window and no recency weighting, so a strong early record keeps propping this figure up long after recent results have deteriorated.
- `rolling_score` takes the first three candidates of the ordered set, or all of them when fewer than three exist. The raw recency weights are 0.5 for the newest, 0.3 for the next and 0.2 for the third; the weights actually used are those raw weights truncated to the number of candidates available and then **renormalised** by dividing each by the sum of the truncated weights. `rolling_score` is the sum of each candidate's `composite_score` multiplied by its renormalised weight, rounded half up to two decimal places. Renormalisation matters below three feedbacks: with exactly two candidates the weights are 0.5 divided by 0.8, which is 0.625, and 0.3 divided by 0.8, which is 0.375 — not 0.5 and 0.3. Older feedbacks drop out of this figure entirely once a fourth arrives.

Filing feedback also increments the speaker's `feedback_count` by one. Until the first feedback exists both `rolling_score` and `lifetime_score` are null; a computed performance read for a speaker with no feedback answers with a null `score` and a `feedback_count` of 0. That computed read returns six fields — `speaker_id`, the `variant` that was applied, the resulting `score`, `feedback_count`, `roster_tier` and `default_commission_pct` — and accepts a `variant` query parameter of `ROLLING` or `LIFETIME`, defaulting to `ROLLING`.

Tiering is the last hop. It re-runs at the end of a delivery, after `engagements_delivered_count` has been incremented, and at the end of a feedback filing, after `rolling_score` has been rewritten. Both conditions of a tier must hold and the highest satisfied tier wins: `GOLD` requires `engagements_delivered_count` of at least 4 **and** a `rolling_score` of at least 4.50; `SILVER` requires `engagements_delivered_count` of at least 2 **and** a `rolling_score` of at least 4.00; otherwise the speaker is `BRONZE`, and a speaker whose `rolling_score` is still null is always `BRONZE`. The gate reads the rolling figure only — never the lifetime one — and it compares against the already-rounded two-decimal value. `default_commission_pct` is then rewritten from the tier: 0.25 for `BRONZE`, 0.22 for `SILVER`, 0.20 for `GOLD`. The movement runs both ways: a poor rating that drags `rolling_score` down to 4 hundredths below the silver gate, that is to 3.99, demotes a `SILVER` speaker back to `BRONZE` and lifts their `default_commission_pct` back up to 0.25. Engagements already contracted are unaffected, since they carry their own `commission_pct_snapshot`.

Commission protection closes the loop. When a client books a speaker directly after the bureau introduced them, a `BureauAdmin` or `BookingAgent` opens a claim naming the `client_id` accused, the `speaker_id` rebooked, the `source_engagement_id` of the bureau-brokered engagement that opened the protection window, the `direct_event_date_utc` of the directly booked event, and the `direct_fee_cents` the client paid the speaker directly. The source engagement must be `DELIVERED` and must carry a non-null `commission_pct_snapshot`, and at most one claim in `OPEN` or `UPHELD` may exist for any given combination of client, speaker and source engagement — a second is refused with `ERR_DUPLICATE_CLAIM`. At creation the server computes and locks three derived figures. `days_after_source` is the whole days from the source engagement's `event_end_utc` to `direct_event_date_utc`, computed as the difference in seconds divided by 86400 and floored; a direct event on or before the source engagement's end therefore gives a count of zero or less, which sits comfortably inside the full-protection band. `protection_factor` is 1.00 when `days_after_source` is at most 180 — the first six months — and 0.50 when `days_after_source` is greater than 180 but at most 365; a `days_after_source` greater than 365 means the protection has lapsed entirely and the claim is refused with `ERR_OUTSIDE_PROTECTION_WINDOW`. `commission_due_cents` is `direct_fee_cents` multiplied by the source engagement's `commission_pct_snapshot` multiplied by `protection_factor`, that single triple product rounded half up to a whole number of cents. The rate used is deliberately the source engagement's pinned snapshot and not the speaker's current `default_commission_pct`: a speaker promoted to `SILVER` after the source engagement was contracted still owes commission at the rate that engagement was written at. A new claim starts in `status` `OPEN` with `settled_cents` null.

Adjudication is a `BureauAdmin` prerogative, driven by an `outcome` with an optional `resolution_note`. `DISMISS` requires the claim to be `OPEN`, drives `OPEN → DISMISSED`, and leaves the client's `circumvention_strikes` unchanged. `UPHOLD` also requires the claim to be `OPEN`, drives `OPEN → UPHELD`, and sets off a four-hop cascade: the client's `circumvention_strikes` rises by one; upon reaching the threshold of 2 strikes the client's `credit_status` becomes `HOLD`; and because the posture became `HOLD`, every inquiry of that client whose `status` is `QUALIFIED` moves to `BLOCKED` — leaving inquiries in `RECEIVED` or `PROPOSED` alone, as noted in §3.2. A held client can no longer have inquiries qualified, cannot select options, and cannot sign the client leg of an agreement. `SETTLE` requires the claim to already be `UPHELD` and carries `settled_cents`, the amount actually collected, which must be at least 0 and no greater than the claim's `commission_due_cents`; a value outside that range is refused with `ERR_INVALID_REQUEST`. Settlement drives `UPHELD → SETTLED`, writes `settled_cents`, and does **not** add a further strike, because the uphold already counted it. Applying `UPHOLD` or `DISMISS` to a claim that is not `OPEN`, or `SETTLE` to a claim that is not `UPHELD`, is refused with `ERR_CLAIM_NOT_OPEN`.

## 4. Endpoint Definitions

Operations that bring a new resource into existence — registering a speaker or a client, posting a calendar hold, recording an inquiry, opening a proposal round, adding a quoted option, selecting an option (which mints the engagement), drafting an agreement, submitting a travel receipt, filing feedback, or opening a circumvention claim — answer with `201 Created`. Operations that modify an existing resource, including every state-advancing action, every payment, every payout and every roster or client edit, answer with `200 OK`. Reads answer with `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/speakers` | Register a speaker on the roster with topic taxonomy, fee range and travel requirements | BureauAdmin |
| GET | `/speakers` | List roster speakers, optionally filtered by topic code, roster status or tier | BureauAdmin, BookingAgent |
| GET | `/speakers/{speakerId}` | Read one roster speaker including derived tier, commission rate and conserved held-days total | BureauAdmin, BookingAgent, Speaker |
| PATCH | `/speakers/{speakerId}` | Maintain roster posture and travel/fee terms | BureauAdmin |
| GET | `/speakers/{speakerId}/performance` | Computed read of the speaker performance score for the requested variant | BureauAdmin, BookingAgent, Speaker |
| POST | `/clients` | Register a booking client organisation with its industry code | BureauAdmin |
| GET | `/clients` | List client organisations, optionally filtered by industry or credit posture | BureauAdmin, BookingAgent |
| GET | `/clients/{clientId}` | Read one client including outstanding balance and circumvention strikes | BureauAdmin, BookingAgent, Client |
| PATCH | `/clients/{clientId}` | Adjust client credit posture or contact address | BureauAdmin |
| POST | `/speaker-holds` | Post a manual blackout hold on a speaker's calendar | BureauAdmin, BookingAgent |
| GET | `/speaker-holds` | List calendar holds | BureauAdmin, BookingAgent, Speaker |
| GET | `/speaker-holds/{holdId}` | Read one calendar hold including its day span | BureauAdmin, BookingAgent, Speaker |
| POST | `/inquiries` | Record an inbound client inquiry with topic, event window, audience, objectives and budget | BookingAgent, BureauAdmin |
| GET | `/inquiries` | List inquiries | BureauAdmin, BookingAgent, Client |
| GET | `/inquiries/{inquiryId}` | Read one inquiry including the version used as the proposal-creation concurrency token | BureauAdmin, BookingAgent, Client |
| POST | `/inquiries/{inquiryId}/qualify` | Qualify or disqualify an inquiry against lead time, budget floor and client credit posture | BookingAgent |
| POST | `/inquiries/{inquiryId}/proposals` | Open a new proposal round on a qualified inquiry, superseding every live package | BookingAgent |
| GET | `/proposals` | List proposals | BureauAdmin, BookingAgent, Client |
| GET | `/proposals/{proposalId}` | Read one proposal including round, revision count, option count and validity instant | BureauAdmin, BookingAgent, Client |
| POST | `/proposal-options` | Add one speaker option with its fee quotation to a draft or revision-requested package | BookingAgent |
| GET | `/proposal-options` | List quoted speaker options | BureauAdmin, BookingAgent, Client |
| GET | `/proposal-options/{optionId}` | Read one quoted speaker option | BureauAdmin, BookingAgent, Client |
| POST | `/proposals/{proposalId}/present` | Present the quotation package to the client | BookingAgent |
| POST | `/proposals/{proposalId}/request-revision` | Client asks for a re-quote | Client |
| POST | `/proposals/{proposalId}/decline` | Client declines the whole quotation package | Client |
| POST | `/proposals/{proposalId}/select` | Client selects one quoted speaker option, which mints the engagement | Client |
| GET | `/engagements` | List engagements | BureauAdmin, BookingAgent, Speaker, Client |
| GET | `/engagements/{engagementId}` | Read one engagement including both state dimensions, commission snapshot and settlement figures | BureauAdmin, BookingAgent, Speaker, Client |
| POST | `/engagements/{engagementId}/confirm` | Speaker accepts the booking | Speaker |
| POST | `/engagements/{engagementId}/decline` | Speaker refuses the booking, re-opening the package for another selection | Speaker |
| POST | `/engagements/{engagementId}/contracts` | Draft the speaker agreement with cancellation ladder, travel policy, recording rights and exclusivity term | BookingAgent |
| POST | `/engagements/{engagementId}/travel-expenses` | Submit a travel receipt against a confirmed or contracted engagement | Speaker, BookingAgent |
| POST | `/engagements/{engagementId}/deliver` | Mark the engagement delivered after the event window closes | BookingAgent |
| POST | `/engagements/{engagementId}/cancel` | Cancel a confirmed or contracted engagement | Client, Speaker, BureauAdmin |
| POST | `/engagements/{engagementId}/feedback` | Client files engagement feedback, which re-scores the speaker and may re-tier the roster | Client |
| POST | `/engagements/{engagementId}/commission-adjustments` | Re-price a contracted engagement's commission rate under four-eyes control | BookingAgent, BureauAdmin |
| GET | `/contracts` | List speaker agreements | BureauAdmin, BookingAgent, Speaker, Client |
| GET | `/contracts/{contractId}` | Read one speaker agreement including both signature stamps and the execution instant | BureauAdmin, BookingAgent, Speaker, Client |
| POST | `/contracts/{contractId}/send` | Send the drafted agreement out for signature | BookingAgent |
| POST | `/contracts/{contractId}/sign` | Sign one leg of the agreement | Speaker, Client |
| GET | `/travel-expenses` | List travel expense submissions | BureauAdmin, BookingAgent, Speaker |
| GET | `/travel-expenses/{expenseId}` | Read one travel expense including its computed reimbursable amount | BureauAdmin, BookingAgent, Speaker |
| POST | `/travel-expenses/{expenseId}/approve` | Approve a travel receipt under the agreement's travel policy | BookingAgent |
| POST | `/travel-expenses/{expenseId}/reject` | Reject a travel receipt | BookingAgent |
| GET | `/feedback` | List engagement feedback | BureauAdmin, BookingAgent, Speaker, Client |
| GET | `/feedback/{feedbackId}` | Read one immutable feedback record including its composite score | BureauAdmin, BookingAgent, Speaker, Client |
| GET | `/invoices` | List invoices | BureauAdmin, BookingAgent, Client |
| GET | `/invoices/{invoiceId}` | Read one invoice including its per-line amounts and surcharge | BureauAdmin, BookingAgent, Client |
| POST | `/invoices/{invoiceId}/payments` | Record a client payment against an issued invoice | Client, BureauAdmin |
| POST | `/invoices/{invoiceId}/void` | Void an unpaid issued invoice, compensating every ledger effect of issuance | BureauAdmin |
| GET | `/remittances` | List speaker remittances | BureauAdmin, BookingAgent, Speaker |
| GET | `/remittances/{remittanceId}` | Read one remittance including gross fee, withheld commission and travel pass-through | BureauAdmin, BookingAgent, Speaker |
| POST | `/remittances/{remittanceId}/pay` | Pay out an approved remittance | BureauAdmin |
| GET | `/exclusivity-grants` | List exclusivity grants | BureauAdmin, BookingAgent, Speaker, Client |
| GET | `/exclusivity-grants/{grantId}` | Read one exclusivity grant including its half-open effective window | BureauAdmin, BookingAgent, Speaker, Client |
| POST | `/exclusivity-grants/{grantId}/waive` | Waive an active exclusivity grant so the speaker can be confirmed for a competing client | BureauAdmin |
| POST | `/circumvention-claims` | Open a commission-protection claim after a client rebooks a speaker directly | BureauAdmin, BookingAgent |
| GET | `/circumvention-claims` | List commission-protection claims | BureauAdmin, BookingAgent |
| GET | `/circumvention-claims/{claimId}` | Read one commission-protection claim including protection factor and commission due | BureauAdmin, BookingAgent |
| POST | `/circumvention-claims/{claimId}/resolve` | Uphold, dismiss or settle a commission-protection claim | BureauAdmin |
| POST | `/_clock/set_current_utc` | Set the server's logical clock; the startup default is exactly 2026-08-01T00:00:00Z and wall-clock time is never consulted | BureauAdmin, BookingAgent, Speaker, Client |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_EVENT_WINDOW_INVALID` | 422 |
| `ERR_RECORDING_FEE_NOT_ALLOWED` | 422 |
| `ERR_RECORDING_FEE_REQUIRED` | 422 |
| `ERR_COMMISSION_PCT_OUT_OF_RANGE` | 422 |
| `ERR_SPEAKER_NOT_FOUND` | 404 |
| `ERR_CLIENT_NOT_FOUND` | 404 |
| `ERR_INQUIRY_NOT_FOUND` | 404 |
| `ERR_PROPOSAL_NOT_FOUND` | 404 |
| `ERR_OPTION_NOT_FOUND` | 404 |
| `ERR_ENGAGEMENT_NOT_FOUND` | 404 |
| `ERR_CONTRACT_NOT_FOUND` | 404 |
| `ERR_HOLD_NOT_FOUND` | 404 |
| `ERR_TRAVEL_EXPENSE_NOT_FOUND` | 404 |
| `ERR_INVOICE_NOT_FOUND` | 404 |
| `ERR_REMITTANCE_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_GRANT_NOT_FOUND` | 404 |
| `ERR_FEEDBACK_NOT_FOUND` | 404 |
| `ERR_STALE_INQUIRY_VERSION` | 412 |
| `ERR_STALE_ENGAGEMENT_VERSION` | 412 |
| `ERR_INQUIRY_STATE_INVALID` | 409 |
| `ERR_PROPOSAL_STATE_INVALID` | 409 |
| `ERR_ENGAGEMENT_STATE_INVALID` | 409 |
| `ERR_ENGAGEMENT_ALREADY_TERMINAL` | 409 |
| `ERR_CONTRACT_STATE_INVALID` | 409 |
| `ERR_PARTY_ALREADY_SIGNED` | 409 |
| `ERR_TRAVEL_EXPENSE_STATE_INVALID` | 409 |
| `ERR_INVOICE_NOT_PAYABLE` | 409 |
| `ERR_REMITTANCE_NOT_APPROVED` | 409 |
| `ERR_CLAIM_NOT_OPEN` | 409 |
| `ERR_GRANT_NOT_ACTIVE` | 409 |
| `ERR_FEEDBACK_ALREADY_SUBMITTED` | 409 |
| `ERR_OPTION_NOT_IN_PROPOSAL` | 409 |
| `ERR_CLIENT_CREDIT_HOLD` | 409 |
| `ERR_SPEAKER_NOT_ACTIVE` | 409 |
| `ERR_TOPIC_NOT_IN_ROSTER` | 409 |
| `ERR_CONTRACT_NOT_EXECUTED` | 409 |
| `ERR_SPEAKER_TAX_FORM_MISSING` | 409 |
| `ERR_EXCLUSIVITY_CONFLICT` | 409 |
| `ERR_SPEAKER_CALENDAR_CONFLICT` | 409 |
| `ERR_INSUFFICIENT_LEAD_TIME` | 409 |
| `ERR_PROPOSAL_EXPIRED` | 409 |
| `ERR_EVENT_NOT_ENDED` | 409 |
| `ERR_OUTSIDE_PROTECTION_WINDOW` | 409 |
| `ERR_PROPOSAL_NO_OPTIONS` | 409 |
| `ERR_OPTION_LIMIT_REACHED` | 409 |
| `ERR_DUPLICATE_SPEAKER_OPTION` | 409 |
| `ERR_DUPLICATE_RANK` | 409 |
| `ERR_REVISION_LIMIT_REACHED` | 409 |
| `ERR_DUPLICATE_CLAIM` | 409 |
| `ERR_BUDGET_BELOW_FLOOR` | 409 |
| `ERR_FEE_OUTSIDE_SPEAKER_RANGE` | 409 |
| `ERR_QUOTE_EXCEEDS_BUDGET` | 409 |
| `ERR_OVERPAYMENT` | 409 |
