# Medical Fundraiser API — Product Requirements Document

## 1. Introduction

This document specifies the backend service for a personal-cause and medical crowdfunding platform in the spirit of consumer "give-here" sites. The product lets an **Organizer** publish a fundraising **Campaign** on behalf of a named **Beneficiary**, collect gifts from the public, keep supporters informed with updates and thank-you notes, and — once the beneficiary has passed identity checks and connected a payout account — draw the raised money out through Stripe payouts. Woven through that happy path is a second, adversarial reality: donors dispute charges, fraud is discovered after the fact, refunds claw money back out of a campaign, and a Trust & Safety function must be able to freeze money in place while an investigation runs.

The hard part of this domain is money that is simultaneously raised, reserved, committed, disputed, and locked — and the platform's obligation to never pay out more than a campaign can safely support. Two independent notions of "how much can this campaign withdraw" coexist: an optimistic one used to keep the ledger honest against over-commitment, and a pessimistic one enforced at the moment a withdrawal is requested. Every donation, refund, hold, and dispute nudges those numbers, and a payout that was legitimate yesterday can become over-committed today. The API is therefore written as an event-sourced ledger with immediate consistency: each mutation recomputes the affected campaign's derived money fields in place, cascades any consequences (freezing postures, holding payouts, cancelling in-flight withdrawals), and advances version counters that guard concurrent editors.

A final concern is disclosure and trust: donors are told whether their gift is tax-deductible, organizers carry a computed risk score that Trust & Safety watches, and a logical clock (rather than wall-clock time) drives every time-sensitive rule so that the system's behavior is fully reproducible.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. If either header is missing, or `X-User-Role` is not one of the known roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the named role is not permitted to invoke the endpoint, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly six roles, spelled precisely as follows: `Guest`, `Organizer`, `Beneficiary`, `Donor`, `TrustSafetyAgent`, and `PlatformAdmin`.

- A `Guest` is an unauthenticated visitor. `Guest` is the role used to register the three actor accounts (creating an organizer, a beneficiary, or a donor) and to read any public resource. `X-User-ID` for a `Guest` is an opaque identifier not tied to any persisted entity; the server does not compare it to any record's `id`.
- When `X-User-Role` is `Organizer`, `X-User-ID` is the `id` of the acting `Organizer`; ownership checks on any resource that references an organizer compare the resource's organizer foreign key to `X-User-ID`.
- When `X-User-Role` is `Beneficiary`, `X-User-ID` is the `id` of the acting `Beneficiary`; ownership checks on any resource that references a beneficiary compare that reference to `X-User-ID`.
- When `X-User-Role` is `Donor`, `X-User-ID` is the `id` of the acting `Donor`; a donation's `donor_id` must equal the caller's `X-User-ID`, and refund/dispute participation is checked the same way.
- When `X-User-Role` is `TrustSafetyAgent`, `X-User-ID` is an opaque operational identifier not tied to any persisted entity. The server may record it for audit but does not compare it to any entity's `id`.
- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is likewise an opaque operational identifier not tied to any persisted entity. `PlatformAdmin` is an operational superset that drives Stripe payout processing, feature placements, and the logical clock; the server does not compare its `X-User-ID` to any entity's `id`.

Ownership and team-role failures — an acting user who is neither the resource owner nor a sufficiently-privileged team member — are reported as `ERR_FORBIDDEN` (HTTP 403). A donation whose `donor_id` does not match the acting donor's `X-User-ID` is a distinct failure, `ERR_DONOR_MISMATCH` (HTTP 403).

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

All list endpoints accept two query parameters: `limit` and `offset`. `limit` defaults to 10, may be no smaller than 1, and may be no larger than 100. `offset` defaults to 0 and has a minimum of 0. Results are returned in ascending order of `created_at` (oldest first) unless an endpoint's narrative states otherwise. The `meta` block of a list response carries `limit`, `offset`, `total_count` (the total number of records matching the query before pagination), and `has_more` (true when records remain beyond the current page).

### 2.4. Common Resource Properties and Versioning

Every resource carries a server-minted `id` — a UUID with no type prefix — and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Most resources additionally carry an `updated_at` timestamp (same format), refreshed on every mutation, and an integer `version` that starts at 1 on creation and increases by one on every mutation that changes the resource.

Two resource types are deliberately lightweight and carry **only** `id` and `created_at` — they have no `updated_at` and no `version` field at all, because they are immutable journal entries once written: the campaign `Update`/thank-you note, and the `Refund` record. All other resources — organizers, beneficiaries, donors, campaigns, team members, donations, payouts, disputes, holds, and feature placements — carry the full set of common properties.

Because derived money fields on a campaign are recomputed by cascades (a settled payout, an upheld dispute, a placed hold), those cascades silently advance the campaign's `version` even when no organizer touched the campaign directly. That behavior is the backbone of the concurrency control described in §2.7.

### 2.5. Monetary Precision, Fees, and Reserves

All monetary amounts are stored and returned as **integer cents**; there are no fractional cents anywhere in the system. Two distinct rounding disciplines apply and must not be interchanged:

- The processing-fee gross-up (§3.4) divides by a rate and rounds the resulting total **up to the next whole cent** (ceiling).
- The chargeback reserve rounds **half up** to a whole cent: a computed value whose fractional part is exactly one-half rounds away from zero.

A structural rule governs any reserve total spanning multiple donations: the reserve is rounded **per donation and then summed**, never computed by multiplying a summed net figure by the reserve rate. The two approaches can differ by a cent or more, and only the per-donation-then-sum result is correct.

### 2.6. The Campaign Ledger: Raised, Reserved, Committed, Disputed, and Locked

A campaign exposes a family of computed money fields, each recomputed immediately whenever a donation, refund, payout, hold, or dispute changes. `raised_cents` is the sum of `net_to_campaign_cents` over the campaign's `CAPTURED` donations. `reserve_total_cents` is the per-donation-then-summed chargeback reserve over those same `CAPTURED` donations. `committed_cents` is the sum of `amount_cents` over the campaign's payouts whose status is `REQUESTED`, `PROCESSING`, or `PAID`. `disputed_locked_cents` is the sum of `net_to_campaign_cents` over `CAPTURED` donations that currently carry a dispute in status `OPEN`, `UNDER_REVIEW`, or `NEEDS_INFO`. `hold_locked_cents` is the sum of `locked_amount_cents` over the campaign's `ACTIVE` holds. `paid_out_cents` is the sum of `amount_cents` over the campaign's payouts whose status is currently `PAID`; because reversing a payout moves it out of the `PAID` status, a `REVERSED` payout contributes nothing to this sum (no separate subtraction is applied on top of that).

From these, two availability views are derived, and the distinction between them is load-bearing:

- **Provisional (optimistic) availability**, `provisional_available_cents`, equals `raised_cents` minus `reserve_total_cents` minus `committed_cents`. It ignores open disputes and active holds. It is the figure the platform uses to detect over-commitment: whenever a recompute leaves it below zero, in-flight payouts are pulled back (§3.7).
- **Settled (pessimistic) availability**, `settled_available_cents`, equals `provisional_available_cents` minus `disputed_locked_cents` minus `hold_locked_cents`. It is the figure enforced at the moment a withdrawal is requested or resumed.

### 2.7. Optimistic Concurrency Control on Campaigns

Two write operations are guarded against acting on a stale view of a campaign, and both require a non-optional integer field `expected_campaign_version` in their request body carrying the client's last observed campaign `version`:

1. Editing a campaign's `title`, `story`, or `goal_cents` must carry `expected_campaign_version` equal to the campaign's current `version`. If a cascade (an upheld dispute, a placed hold, a settled payout) or another editor has advanced the version since the client last read the campaign, the edit is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than clobbering the newer state.
2. Requesting a payout must carry `expected_campaign_version` equal to the campaign's current `version`. If the campaign's version has advanced since the client computed the available balance — because another payout was created, a refund posted, or a hold placed — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), because the requester's view of the available balance is stale and the payout would otherwise draw against a balance that no longer exists.

No other endpoint takes a version field. A successful campaign edit and a successful payout request each increment the campaign's `version` by one.

### 2.8. Payout Posture and Cascading Freeze Propagation

Independently of its lifecycle, every campaign carries a computed `payout_posture` with three values — `OPEN`, `HOLD`, and `FROZEN` — recomputed whenever a hold is placed or released or the beneficiary's verification changes. The rule is strictly prioritized: if the campaign's beneficiary is in verification status `REJECTED`, the posture is `FROZEN`; otherwise, if the campaign has at least one `ACTIVE` hold, the posture is `HOLD`; otherwise the posture is `OPEN`.

Posture changes cascade. When a beneficiary is rejected, every campaign of that beneficiary is driven to `FROZEN`, and — as a second-level cascade — each such campaign's payouts in status `REQUESTED`, `PROCESSING`, or `ON_HOLD` are moved to `CANCELLED`. The same two-level cascade fires whether the rejection is a first-time denial of a pending beneficiary or a Trust & Safety revocation of a previously verified one. Conversely, when a rejected beneficiary is later re-approved to `VERIFIED` and no `ACTIVE` holds remain, the affected campaigns recompute back to `OPEN`. Each posture recompute refreshes the campaign's `updated_at` and advances its `version`.

### 2.9. Organizer Risk Scoring

Each organizer exposes two computed risk scores, both integers clamped to the range 0 through 100 (the score ceiling is 100). Both are derived from the same aggregates: the organizer's `total_dispute_count` (the count of disputes in any status on donations belonging to campaigns this organizer owns), `upheld_dispute_count` (the count of those disputes whose status is `UPHELD`), `refunded_amount_cents` (the sum of refund amounts across those campaigns' donations), `raised_cents` (the organizer's total net raised across `CAPTURED` donations), and `has_unverified_beneficiary` (true when at least one of the organizer's campaigns has a beneficiary whose verification status is anything other than `VERIFIED`).

The scoring proceeds as follows. First compute a refund ratio: `refunded_amount_cents` divided by the larger of 1 and `raised_cents` (the denominator floor of 1 guards against division by zero). Then form a raw score as 15 times the dispute count in play, plus the half-up rounding of 50 multiplied by the smaller of 1.0 and that refund ratio. If `has_unverified_beneficiary` is true, add a penalty of 20 to the raw score. Finally, clamp the raw score to no less than 0 and no more than 100.

The two variants differ only in which dispute count feeds the "15 times the dispute count" term. The **strict** score, `strict_risk_score`, uses `total_dispute_count` — it counts every dispute, including those still `OPEN` and those already `REJECTED`. The **lenient** score, `lenient_risk_score`, uses `upheld_dispute_count` — it counts only disputes resolved as `UPHELD`. Both scores are recomputed on any dispute status change, refund creation, or beneficiary verification change, and both are surfaced when an organizer is fetched.

### 2.10. Resource Existence, Validation Ordering, and the Logical Clock

Every referenced resource — whether named in the URL path or in the request body — must exist; a missing resource yields `ERR_NOT_FOUND` (HTTP 404). Path and body references are validated left to right, so the leftmost missing reference is the one reported.

When several checks could fail on one request, they are evaluated in a fixed priority order, and the first failure is the one returned:

1. Authentication of the `X-User-ID`/`X-User-Role` headers (`ERR_UNAUTHENTICATED`, 401).
2. Role authorization for the endpoint (`ERR_UNAUTHORIZED`, 403).
3. Request-body well-formedness — required fields present, enums valid, integer and datetime types correct (`ERR_INVALID_REQUEST`, 400).
4. Existence of every referenced resource, left to right (`ERR_NOT_FOUND`, 404).
5. Ownership and team-role sufficiency (`ERR_FORBIDDEN`, 403).
6. Target-resource state validity for the requested transition, including a campaign being `ACTIVE` before a donation is accepted (`ERR_INVALID_STATE`, 409; the donation-specific variant is `ERR_CAMPAIGN_NOT_ACTIVE`, 409).
7. Payout-posture safety — posture `OPEN` for payout operations (`ERR_PAYOUT_ON_HOLD`, 409) and not `FROZEN` for writes to a frozen campaign or its children (`ERR_CAMPAIGN_FROZEN`, 409).
8. Beneficiary verification readiness for payouts (`ERR_BENEFICIARY_NOT_VERIFIED`, 409).
9. Simple field constraints — a positive campaign goal (`ERR_GOAL_INVALID`, 422) and a valid placement window (`ERR_WINDOW_INVALID`, 422).
10. Donation minimum amount (`ERR_AMOUNT_BELOW_MIN`, 422).
11. Sufficient settled availability for a payout (`ERR_INSUFFICIENT_AVAILABLE`, 402).
12. Feature-slot conflict (`ERR_SLOT_CONFLICT`, 409) and payout cooldown (`ERR_PAYOUT_COOLDOWN`, 409).
13. Duplicate team membership (`ERR_DUPLICATE_TEAM_MEMBER`, 409).
14. Donor identity match on a donation (`ERR_DONOR_MISMATCH`, 403).
15. Optimistic-concurrency version match (`ERR_STALE_VERSION`, 412).

All time-sensitive behavior reads a **logical clock**, never wall-clock time. At server startup the clock reads exactly `2026-03-01T00:00:00Z`, and it holds that value until an administrator explicitly advances it. An admin-only test-driving capability sets the clock to a supplied `to_iso8601` instant. Advancing the clock has a side effect: any `BOOKED` feature placement whose window end is at or before the new clock value is expired (§3.8).

## 3. Business Logic & Workflows

### 3.1. Registering Actors and Preparing a Beneficiary to Receive Funds

The platform is populated by three kinds of actor account, all registered through the guest surface. Registering an organizer supplies a `display_name` and an `email`; the new organizer's dispute, refund, and risk aggregates all begin at zero. Registering a donor supplies a `display_name` and an `email`, and may optionally set `is_anonymous_default`, which controls whether that donor's future gifts hide their identity by default; when omitted it is false. Registering a beneficiary supplies a `legal_name` (used for identity checks) and an `email`; the new beneficiary begins with verification status `UNVERIFIED` and no connected payout account (`stripe_account_ref` is null).

Before any money can leave the platform, a beneficiary must both connect a payout account and pass identity review. Connecting the account attaches a `stripe_account_ref`; this may be performed by the beneficiary themselves or by a platform administrator, and it recomputes the beneficiary's `withdrawal_ready` flag. `withdrawal_ready` is true exactly when the beneficiary's verification status is `VERIFIED` and `stripe_account_ref` is not null.

Verification is a small state machine on the beneficiary's `verification_status`. Submitting for review moves an `UNVERIFIED` or `REJECTED` beneficiary to `PENDING`; this is available only once a payout account is connected, and attempting it while `stripe_account_ref` is still null is rejected with `ERR_WITHDRAWAL_NOT_READY`. A Trust & Safety agent then either approves a `PENDING` beneficiary to `VERIFIED`, or rejects it. Approval — valid only from `PENDING`, otherwise `ERR_INVALID_STATE` — additionally recomputes the payout posture of every campaign of that beneficiary, which can lift a previously `FROZEN` campaign back toward `OPEN`. Rejection is valid from either `PENDING` or `VERIFIED` (the latter being a revocation on discovered fraud), otherwise `ERR_INVALID_STATE`; it records the supplied `reason`, and it drives the freeze cascade described in §2.8 — every campaign of that beneficiary becomes `FROZEN`, and each such campaign's payouts in `REQUESTED`, `PROCESSING`, or `ON_HOLD` are `CANCELLED`. A resubmission after rejection re-enters the `PENDING` queue, forming a review loop.

The most recent successful withdrawal for a beneficiary is remembered in `last_payout_settled_at`, which starts null and is used for the payout cooldown of §3.7. A beneficiary also exposes `total_paid_out_cents`, the sum of amounts over its payouts whose status is currently `PAID`; because reversing a payout moves it out of the `PAID` status, a `REVERSED` payout contributes nothing to this sum (no separate subtraction is applied on top of that).

### 3.2. Creating and Steering a Campaign

An organizer opens a campaign by supplying the `beneficiary_id` of the intended recipient, a `title`, a `story`, a `goal_cents` target, and a `category` (one of `MEDICAL`, `MEMORIAL`, `EMERGENCY`, or `OTHER`). The organizer may also declare `is_charity`; when omitted it is false. The goal must be strictly greater than zero, otherwise the creation is rejected with `ERR_GOAL_INVALID`. A new campaign is born in lifecycle status `DRAFT` with payout posture `OPEN` and every money field at zero; its `organizer_id` is taken from the creator's `X-User-ID`, and the same creating organizer is simultaneously recorded as the campaign's initial team member with the owner role. The campaign's tax disclosure is fixed at creation from `is_charity` (see §3.4).

A campaign carries a public `tax_disclosure` string, `TAX_DEDUCTIBLE` when `is_charity` is true and `NOT_TAX_DEDUCTIBLE` otherwise, surfaced so donors are never misled about deductibility.

The lifecycle axis, `lifecycle_status`, moves as follows. Publishing takes a `DRAFT` campaign to `ACTIVE` and opens it to donations; publishing is available only to an organizer who is an `ACTIVE` team member holding the owner role on that campaign (otherwise `ERR_FORBIDDEN`) and requires the goal to be positive. Pausing takes an `ACTIVE` campaign to `PAUSED`; resuming takes a `PAUSED` campaign back to `ACTIVE`; each requires its exact starting state, otherwise `ERR_INVALID_STATE`. Completing takes a campaign in either `ACTIVE` or `PAUSED` to the terminal `COMPLETED` state, after which new donations are refused but payouts may still be drawn; a completion attempt from any other state is `ERR_INVALID_STATE`. Cancelling takes a campaign in `DRAFT`, `ACTIVE`, or `PAUSED` to the terminal `CANCELLED` state (otherwise `ERR_INVALID_STATE`); cancellation additionally cascades, moving every payout of that campaign in status `REQUESTED`, `PROCESSING`, or `ON_HOLD` to `CANCELLED`.

Editing a campaign's `title`, `story`, or `goal_cents` is an owner operation guarded by optimistic concurrency: the edit body must carry `expected_campaign_version` matching the current `version`, as detailed in §2.7, and a successful edit advances the version by one.

### 3.3. The Campaign Team

A campaign's team is a set of memberships linking organizers to the campaign. Adding a member supplies the `campaign_id`, the `organizer_id` to add, and a `team_role` — one of `OWNER`, `CO_ORGANIZER`, or `WITHDRAWAL_MANAGER`. A new membership is `ACTIVE`. A given organizer may hold at most one `ACTIVE` membership on a given campaign; a second `ACTIVE` membership for the same organizer on the same campaign is rejected with `ERR_DUPLICATE_TEAM_MEMBER`. Removing a member transitions its `status` from `ACTIVE` to `REMOVED`. Team memberships are what the ownership checks of §2.1 consult when deciding whether an acting organizer may steer a campaign.

### 3.4. Donations, Tips, Processing Fees, and Tax Receipts

A donor gifts to a campaign by supplying the `campaign_id`, their own `donor_id` (which must equal the acting donor's `X-User-ID`, otherwise `ERR_DONOR_MISMATCH`), an `amount_cents` gift that goes to the campaign, an optional `tip_cents` platform tip that goes to the platform rather than the campaign (defaulting to zero when omitted), and an optional `is_anonymous` flag; when `is_anonymous` is omitted it falls back to the donor's `is_anonymous_default`. Donations are accepted only while the campaign's `lifecycle_status` is `ACTIVE`; a gift to any other state is refused with `ERR_CAMPAIGN_NOT_ACTIVE`. The gift itself must be at least one dollar — 100 cents — otherwise it is rejected with `ERR_AMOUNT_BELOW_MIN`.

At capture the platform computes the charge breakdown, whose evaluation order is pinned because the processing fee looks self-referential — it is a percentage of a total that itself includes the fee. First form the subtotal as `amount_cents` plus `tip_cents`. Then compute `total_charged_cents` — the amount the donor's card is actually charged — by taking the subtotal plus a fixed 30-cent-per-transaction component, dividing that by one minus the processing rate of 0.029 (that is, dividing by 0.971), and rounding the quotient **up** to the next whole cent. The `processing_fee_cents` is then the residual: `total_charged_cents` minus the subtotal. The amount credited to the campaign, `net_to_campaign_cents`, is simply the `amount_cents` — the tip flows to the platform and the fee flows to the payment processor, so neither reaches the campaign. Finally the per-donation chargeback reserve, `reserve_cents`, is the half-up rounding of `net_to_campaign_cents` multiplied by the reserve rate of 0.05 (five percent).

A fresh donation is `CAPTURED`. Its `tax_receipt_status` is computed from the parent campaign: `DEDUCTIBLE` when the campaign's `is_charity` is true, `NON_DEDUCTIBLE` otherwise. A donation also carries a `thanked` flag, false at capture, set true when a thank-you note references it (§3.5). Recording a donation recomputes the campaign's `raised_cents`, `reserve_total_cents`, and both availability figures.

### 3.5. Updates and Thank-You Notes

An organizer keeps supporters informed by posting a note carrying the `campaign_id`, an `update_type` — either `UPDATE` for a general campaign update or `THANK_YOU` for a note of thanks — and a `body`. A `THANK_YOU` may optionally target a specific gift by including a `donation_id` (a general `UPDATE` leaves it null). When a `THANK_YOU` names a donation, that donation's `thanked` flag is set to true. These notes are immutable journal entries: they carry only `id` and `created_at`, with no `updated_at` or `version`.

### 3.6. Disputes and Refunds

Two paths pull money back out of a campaign: a direct refund and a dispute that is ultimately upheld.

A refund may be requested by the donor on their own donation, or issued by a Trust & Safety agent or a platform administrator. A direct refund creates a `Refund` record whose `reason` is `REQUESTED_BY_DONOR`, with a null `dispute_id`, and whose `amount_cents` equals the parent donation's `net_to_campaign_cents` — the amount clawed back from the campaign. Refunding is valid only while the donation is `CAPTURED`, otherwise `ERR_INVALID_STATE`; it drives the donation from `CAPTURED` to the terminal `REFUNDED`, and recomputes the campaign's `raised_cents`, `reserve_total_cents`, and both availability figures. A refund record, like an update, carries only `id` and `created_at`.

A dispute is opened on a `CAPTURED` donation by the donor or a Trust & Safety agent, supplying the `donation_id` and a `reason` (one of `FRAUD`, `UNAUTHORIZED`, `NOT_AS_DESCRIBED`, or `OTHER`). A new dispute is `OPEN`, and opening it recomputes the campaign's `disputed_locked_cents`, which pins the disputed donation's net out of settled availability. From there the dispute follows a review cycle driven by Trust & Safety, each step requiring its exact predecessor state, otherwise `ERR_INVALID_STATE`: assigning moves it from `OPEN` to `UNDER_REVIEW`; requesting more information moves it from `UNDER_REVIEW` to `NEEDS_INFO`; the donor then provides information to move it from `NEEDS_INFO` back to `UNDER_REVIEW`, and this loop may repeat.

A dispute ends one of two ways. Rejecting it — valid only from `UNDER_REVIEW`, otherwise `ERR_INVALID_STATE` — records the optional `resolution_note`, leaves the donation `CAPTURED`, and recomputes `disputed_locked_cents` so the donation is unlocked. Upholding it — valid from either `UNDER_REVIEW` or `NEEDS_INFO`, and only while the parent donation is still `CAPTURED` — records the `resolution_note` and then fires a four-level cascade: first it creates a `Refund` with reason `DISPUTE_UPHELD` and amount equal to the donation's `net_to_campaign_cents`; that refund drives the donation from `CAPTURED` to `REFUNDED`; the refund then recomputes the campaign's `raised_cents`, `reserve_total_cents`, `provisional_available_cents`, and `settled_available_cents`; and finally, if the provisional availability has gone negative, in-flight payouts are pulled onto hold as described in §3.7 until it is non-negative again.

### 3.7. Withdrawals: Requesting, Processing, Settling, and Clawing Back

Money leaves a campaign through a payout, requested by an organizer against a campaign. The request supplies the `campaign_id`, an `amount_cents` to withdraw, an optional `scheduled_at` instant (defaulting to the current logical-clock value when omitted), and `expected_campaign_version` for the concurrency guard of §2.7. Several gates apply, in the priority order of §2.10. The campaign's `payout_posture` must be `OPEN`: a `HOLD` or `FROZEN` posture blocks the request with `ERR_PAYOUT_ON_HOLD`, and a write to an otherwise-frozen campaign is `ERR_CAMPAIGN_FROZEN`. The beneficiary must be `VERIFIED` and `withdrawal_ready`, otherwise `ERR_BENEFICIARY_NOT_VERIFIED`. The requested amount must not exceed the campaign's `settled_available_cents` — equality is permitted — otherwise `ERR_INSUFFICIENT_AVAILABLE` (HTTP 402). And a cooldown applies between successive withdrawals to the same beneficiary: if the beneficiary's `last_payout_settled_at` is not null, the earliest permissible schedule is that timestamp plus a full day — 24 hours — and a `scheduled_at` strictly earlier than that boundary is refused with `ERR_PAYOUT_COOLDOWN`; a `scheduled_at` exactly at the boundary is allowed. On success the payout is created in status `REQUESTED`, its `beneficiary_id` is copied from the campaign, the campaign's `version` is advanced by one, and `committed_cents` and the availability figures are recomputed.

Processing a payout, an administrator operation, moves it from `REQUESTED` to `PROCESSING` and submits the funds to Stripe; it requires the payout to be `REQUESTED` (otherwise `ERR_INVALID_STATE`), the campaign posture to be `OPEN` (otherwise `ERR_PAYOUT_ON_HOLD`), and the beneficiary to be `VERIFIED` (otherwise `ERR_BENEFICIARY_NOT_VERIFIED`). Settling, driven by the Stripe webhook, moves a `PROCESSING` payout to the terminal-in-practice `PAID` state: it records the optional `stripe_payout_ref` and stamps `settled_at` from the logical clock, adds the amount to the campaign's `paid_out_cents`, adds it to the beneficiary's `total_paid_out_cents`, and sets the beneficiary's `last_payout_settled_at` to the settle time. A payout that Stripe rejects is failed by an administrator, moving it from `REQUESTED` or `PROCESSING` to `FAILED` and excluding it from `committed_cents`.

Two safety motions run outside the ordinary path. When a refund or hold recompute leaves a campaign's `provisional_available_cents` below zero — the campaign is over-committed — the system automatically pulls payouts in status `REQUESTED` or `PROCESSING` onto `ON_HOLD`, and an `ON_HOLD` payout is excluded from `committed_cents`. The selection is deterministic: payouts are moved newest-first, in descending order of `created_at` (with `created_at` as the sole tie-break), one at a time, and only until `provisional_available_cents` climbs back to zero or above. A held payout is later revived by a Trust & Safety agent, moving it from `ON_HOLD` back to `REQUESTED` — permitted only when it is `ON_HOLD` (otherwise `ERR_INVALID_STATE`), the posture is `OPEN`, and its `amount_cents` does not exceed the campaign's current `settled_available_cents` (otherwise `ERR_INSUFFICIENT_AVAILABLE`) — at which point it re-enters `committed_cents`. Finally, a fraudulent `PAID` payout is clawed back by a Trust & Safety agent, moving it from `PAID` to `REVERSED` (only valid from `PAID`, otherwise `ERR_INVALID_STATE`) and compensating the ledger: the campaign's `paid_out_cents` and the beneficiary's `total_paid_out_cents` are each decremented by the amount. Every payout also records a `stripe_payout_ref` and `settled_at`, both null until settlement.

### 3.8. Trust & Safety Holds and Featured Placements

A Trust & Safety agent may place a hold on a campaign, supplying the `campaign_id`, a `reason`, a `severity` (`STANDARD` or `CRITICAL`), and an optional `locked_amount_cents` (defaulting to zero) that represents the slice of settled availability frozen while the hold stands. A new hold is `ACTIVE`; placing it recomputes the campaign's `hold_locked_cents` and drives the payout posture to `HOLD` unless the campaign is already `FROZEN` by a rejected beneficiary. Releasing a hold moves it from `ACTIVE` to `RELEASED` (only valid from `ACTIVE`, otherwise `ERR_INVALID_STATE`), then recomputes `hold_locked_cents` and the payout posture — which returns to `OPEN` once the campaign's last active hold is gone and its beneficiary is not rejected.

Separately, a platform administrator may feature a campaign in a promotional surface. A feature placement supplies the `campaign_id`, a `category` naming the surface (`HOMEPAGE`, `MEDICAL`, or `EMERGENCY`), a `slot_index` within that surface, and a half-open time window given by `window_start` (inclusive) and `window_end` (exclusive). The window end must be strictly after the window start, otherwise `ERR_WINDOW_INVALID`. A given surface-and-slot pair — the combination of `category` and `slot_index` — is exclusive: a new placement whose window overlaps that of an existing `BOOKED` placement on the same `category` and `slot_index` is rejected with `ERR_SLOT_CONFLICT`. Because the windows are half-open, two placements that merely abut — one ending exactly when the next begins — do not conflict. A new placement is `BOOKED`. An administrator may cancel a `BOOKED` placement, moving it to `CANCELLED` (only valid from `BOOKED`, otherwise `ERR_INVALID_STATE`) and freeing that slot window for re-booking. A placement also expires automatically: whenever the logical clock is advanced to or past a `BOOKED` placement's `window_end`, that placement moves to `EXPIRED`.

## 4. Endpoint Definitions

Creation endpoints return HTTP 201 with the newly created resource; state transitions, edits, and other modifications return HTTP 200 with the updated resource; reads return HTTP 200. The table below is a directory only — request bodies, response side effects, and trigger conditions live in the §2 and §3 narratives above.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |
| POST | `/organizers` | Register an organizer | Guest |
| GET | `/organizers/{id}` | Get an organizer with computed risk scores | Guest, Organizer, Beneficiary, Donor, TrustSafetyAgent, PlatformAdmin |
| POST | `/beneficiaries` | Register a beneficiary | Guest |
| GET | `/beneficiaries/{id}` | Get a beneficiary | Guest, Organizer, Beneficiary, Donor, TrustSafetyAgent, PlatformAdmin |
| POST | `/beneficiaries/{id}/withdrawal-setup` | Attach a connected Stripe account | Beneficiary, PlatformAdmin |
| POST | `/beneficiaries/{id}/submit-verification` | Submit KYC for review | Beneficiary |
| POST | `/beneficiaries/{id}/approve-verification` | Approve KYC | TrustSafetyAgent |
| POST | `/beneficiaries/{id}/reject-verification` | Reject KYC and cascade freeze | TrustSafetyAgent |
| POST | `/donors` | Register a donor | Guest |
| GET | `/donors/{id}` | Get a donor | Guest, Organizer, Beneficiary, Donor, TrustSafetyAgent, PlatformAdmin |
| POST | `/campaigns` | Create a campaign in DRAFT | Organizer |
| GET | `/campaigns/{id}` | Get a campaign with computed money and posture fields | Guest, Organizer, Beneficiary, Donor, TrustSafetyAgent, PlatformAdmin |
| GET | `/campaigns` | List campaigns | Guest, Organizer, Beneficiary, Donor, TrustSafetyAgent, PlatformAdmin |
| PATCH | `/campaigns/{id}` | Edit goal/story/title (OCC-guarded) | Organizer |
| POST | `/campaigns/{id}/publish` | Publish DRAFT to ACTIVE | Organizer |
| POST | `/campaigns/{id}/pause` | Pause ACTIVE to PAUSED | Organizer |
| POST | `/campaigns/{id}/resume` | Resume PAUSED to ACTIVE | Organizer |
| POST | `/campaigns/{id}/complete` | Complete to COMPLETED | Organizer |
| POST | `/campaigns/{id}/cancel` | Cancel to CANCELLED and cancel non-terminal payouts | Organizer |
| POST | `/team-members` | Add a co-organizer or withdrawal manager | Organizer |
| GET | `/team-members/{id}` | Get a team member | Guest, Organizer, Beneficiary, Donor, TrustSafetyAgent, PlatformAdmin |
| GET | `/team-members` | List team members | Guest, Organizer, Beneficiary, Donor, TrustSafetyAgent, PlatformAdmin |
| POST | `/team-members/{id}/remove` | Remove a team member | Organizer |
| POST | `/donations` | Make a donation with optional tip | Donor |
| GET | `/donations/{id}` | Get a donation | Guest, Organizer, Beneficiary, Donor, TrustSafetyAgent, PlatformAdmin |
| GET | `/donations` | List donations | Guest, Organizer, Beneficiary, Donor, TrustSafetyAgent, PlatformAdmin |
| POST | `/donations/{id}/refund` | Refund a donation | Donor, TrustSafetyAgent, PlatformAdmin |
| POST | `/updates` | Post a campaign update or thank-you | Organizer |
| GET | `/updates/{id}` | Get an update | Guest, Organizer, Beneficiary, Donor, TrustSafetyAgent, PlatformAdmin |
| GET | `/updates` | List updates | Guest, Organizer, Beneficiary, Donor, TrustSafetyAgent, PlatformAdmin |
| POST | `/payouts` | Request a Stripe payout (OCC-guarded) | Organizer |
| GET | `/payouts/{id}` | Get a payout | Guest, Organizer, Beneficiary, Donor, TrustSafetyAgent, PlatformAdmin |
| GET | `/payouts` | List payouts | Guest, Organizer, Beneficiary, Donor, TrustSafetyAgent, PlatformAdmin |
| POST | `/payouts/{id}/process` | Move REQUESTED to PROCESSING | PlatformAdmin |
| POST | `/payouts/{id}/settle` | Move PROCESSING to PAID | PlatformAdmin |
| POST | `/payouts/{id}/fail` | Move REQUESTED/PROCESSING to FAILED | PlatformAdmin |
| POST | `/payouts/{id}/resume` | Move ON_HOLD to REQUESTED | TrustSafetyAgent |
| POST | `/payouts/{id}/reverse` | Move PAID to REVERSED | TrustSafetyAgent |
| POST | `/disputes` | Open a dispute on a CAPTURED donation | Donor, TrustSafetyAgent |
| GET | `/disputes/{id}` | Get a dispute | Guest, Organizer, Beneficiary, Donor, TrustSafetyAgent, PlatformAdmin |
| GET | `/disputes` | List disputes | Guest, Organizer, Beneficiary, Donor, TrustSafetyAgent, PlatformAdmin |
| POST | `/disputes/{id}/assign` | Move OPEN to UNDER_REVIEW | TrustSafetyAgent |
| POST | `/disputes/{id}/request-info` | Move UNDER_REVIEW to NEEDS_INFO | TrustSafetyAgent |
| POST | `/disputes/{id}/provide-info` | Move NEEDS_INFO to UNDER_REVIEW | Donor |
| POST | `/disputes/{id}/uphold` | Uphold and cascade refund plus payout hold | TrustSafetyAgent |
| POST | `/disputes/{id}/reject` | Reject a dispute | TrustSafetyAgent |
| GET | `/refunds/{id}` | Get a refund | Guest, Organizer, Beneficiary, Donor, TrustSafetyAgent, PlatformAdmin |
| GET | `/refunds` | List refunds | Guest, Organizer, Beneficiary, Donor, TrustSafetyAgent, PlatformAdmin |
| POST | `/holds` | Place a Trust & Safety hold on a campaign | TrustSafetyAgent |
| GET | `/holds/{id}` | Get a hold | Guest, Organizer, Beneficiary, Donor, TrustSafetyAgent, PlatformAdmin |
| GET | `/holds` | List holds | Guest, Organizer, Beneficiary, Donor, TrustSafetyAgent, PlatformAdmin |
| POST | `/holds/{id}/release` | Release a hold | TrustSafetyAgent |
| POST | `/feature-placements` | Book a campaign into a feature slot | PlatformAdmin |
| GET | `/feature-placements/{id}` | Get a feature placement | Guest, Organizer, Beneficiary, Donor, TrustSafetyAgent, PlatformAdmin |
| GET | `/feature-placements` | List feature placements | Guest, Organizer, Beneficiary, Donor, TrustSafetyAgent, PlatformAdmin |
| POST | `/feature-placements/{id}/cancel` | Cancel a booked placement | PlatformAdmin |

List endpoints accept the pagination parameters `limit` and `offset` plus the filters named in their §3 narratives: campaigns filter by `organizer_id`, `beneficiary_id`, and `lifecycle_status`; team members by `campaign_id` and `organizer_id`; donations by `campaign_id`, `donor_id`, and `status`; updates by `campaign_id` and `donation_id`; payouts by `campaign_id`, `beneficiary_id`, and `status`; disputes by `donation_id` and `status`; refunds by `donation_id` and `dispute_id`; holds by `campaign_id` and `status`; and feature placements by `campaign_id` and `category`.

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_DONOR_MISMATCH` | 403 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CAMPAIGN_NOT_ACTIVE` | 409 |
| `ERR_CAMPAIGN_FROZEN` | 409 |
| `ERR_PAYOUT_ON_HOLD` | 409 |
| `ERR_BENEFICIARY_NOT_VERIFIED` | 409 |
| `ERR_WITHDRAWAL_NOT_READY` | 409 |
| `ERR_GOAL_INVALID` | 422 |
| `ERR_WINDOW_INVALID` | 422 |
| `ERR_AMOUNT_BELOW_MIN` | 422 |
| `ERR_INSUFFICIENT_AVAILABLE` | 402 |
| `ERR_SLOT_CONFLICT` | 409 |
| `ERR_PAYOUT_COOLDOWN` | 409 |
| `ERR_DUPLICATE_TEAM_MEMBER` | 409 |
| `ERR_STALE_VERSION` | 412 |
