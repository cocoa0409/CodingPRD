# HopeFlow

HopeFlow is a backend for charitable organizations running fundraising campaigns. It handles the full donation lifecycle: pledges from prospective donors, incoming contributions, matching grants from corporate sponsors, allocation of funds to specific causes, and disbursements to beneficiaries.

The platform ensures that campaigns stay compliant, funds are tracked accurately, and donors can trust that their money goes where promised. When compliance issues arise, the system restricts operations appropriately until resolved.


## Campaigns

A campaign is the top-level container for all fundraising activity. Creating a campaign accepts a `name` and `fundraising_target`. The created campaign returns an `id`, the provided fields, and computed state: `posture`, `pledge_outstanding`, `contribution_total`, `match_total`, `allocated_total`, `disbursed_total`, and `available_balance`.

Every campaign has a `posture` that controls what operations are allowed. Posture is derived from holds (see Holds section):
- `OPEN` — normal operations
- `RESTRICTED` — contributions and disbursements blocked; pledges and administrative actions allowed
- `FROZEN` — only hold resolution and read operations allowed

A campaign also has a `phase` that tracks its lifecycle: `ACTIVE` or `CLOSED`. New campaigns start `ACTIVE`. Once closed, a campaign cannot be reopened, but disbursements can continue if funds remain and posture allows.

The `available_balance` equals `contribution_total` plus `match_total` minus `disbursed_total`. This is the actual cash available for disbursement. The `allocated_total` tracks how much has been earmarked for specific causes and may exceed `available_balance` if allocations include unfulfilled pledges.


## Pledges

Pledges are promises to donate. They help campaigns forecast expected revenue and can be converted to actual contributions later.

Creating a pledge accepts a `donor_name`, `donor_email`, and `amount`. The pledge returns an `id`, the provided fields, and a `status` of `OUTSTANDING`. Pledges also track `fulfilled_contribution_id` which is null until fulfillment.

A pledge can be in one of these statuses:
- `OUTSTANDING` — awaiting fulfillment
- `FULFILLED` — converted to a contribution
- `LAPSED` — donor indicated they won't fulfill
- `VOIDED` — cancelled by campaign administrator

The campaign's `pledge_outstanding` reflects the sum of amounts from pledges in `OUTSTANDING` status.

Fulfilling a pledge transitions it to `FULFILLED` and links it to the contribution that fulfills it (see Contributions). Lapsing a pledge marks it as `LAPSED`. Voiding a pledge marks it as `VOIDED`. All three actions reduce `pledge_outstanding` by the pledge amount.

Only `OUTSTANDING` pledges can be fulfilled, lapsed, or voided.


## Contributions

Contributions are actual donations received. They're the lifeblood of the campaign.

Creating a contribution accepts `donor_name`, `donor_email`, `gross_amount`, and optionally `fulfills_pledge_id` and `match_eligible`. The platform deducts a 3% processing fee, so `net_amount` equals `gross_amount` minus `fee_amount` (which is 3% of gross, rounded down to the nearest cent). Contributions return an `id`, all provided and computed fields, `status`, `matched_amount`, and an `allocations` array.

A contribution starts in `CLEARED` status. If it fulfills a pledge, that pledge transitions to `FULFILLED` and stores the contribution's id. A contribution can only fulfill an `OUTSTANDING` pledge, and the contribution's `gross_amount` must exactly equal the pledge's `amount`.

The `match_eligible` flag defaults to true. Only match-eligible contributions can receive matching funds from grants (see Grants).

A contribution can be refunded, which transitions it to `REFUNDED` status. Refunding has significant cascading effects:
- The contribution's `net_amount` is subtracted from `contribution_total`
- Any matching funds are clawed back (subtracted from `match_total`)
- All allocations from this contribution are reversed
- If the contribution fulfilled a pledge, that pledge reverts to `OUTSTANDING`

Only `CLEARED` contributions can be refunded.


## Grants

Grants are matching fund programs where corporate sponsors agree to match donations up to a cap.

Creating a grant accepts `sponsor_name`, `match_ratio` (like 1.0 for dollar-for-dollar, or 0.5 for fifty cents per dollar), `cap_amount`, and optionally `min_contribution` (defaults to 0) and `excludes_pledge_fulfillment` (defaults to false). The grant returns an `id`, all provided fields, `matched_so_far`, and `status`.

Grants have these statuses:
- `ACTIVE` — matching new contributions
- `SUSPENDED` — temporarily paused; existing matches preserved
- `REVOKED` — terminated; all previous matches clawed back
- `EXHAUSTED` — reached cap; no more matching

When a match-eligible contribution clears, active grants apply their matching. For each active grant:
1. Skip if `min_contribution` exceeds the contribution's `gross_amount`
2. Skip if `excludes_pledge_fulfillment` is true and the contribution fulfills a pledge
3. Calculate potential match: `gross_amount` × `match_ratio`
4. Cap at remaining grant capacity: `cap_amount` minus `matched_so_far`
5. Add the match amount to the contribution's `matched_amount` and the grant's `matched_so_far`

Matching happens in grant creation order (earliest first) until all grants are processed or capacity is exhausted. If a grant reaches its cap, it transitions to `EXHAUSTED`.

Suspending a grant stops it from matching new contributions but preserves existing matches. Reactivating a suspended grant returns it to `ACTIVE` status (or `EXHAUSTED` if already at cap).

Revoking a grant is severe: it claws back all previous matches. Every contribution that received matching from this grant has its `matched_amount` reduced accordingly. The campaign's `match_total` decreases. Allocations funded by match amounts are reversed proportionally. A revoked grant cannot be reactivated.

Only `ACTIVE` or `SUSPENDED` grants can be suspended, reactivated, or revoked. `EXHAUSTED` grants can only be revoked.


## Causes

Causes are the specific funding goals within a campaign—the things donors' money actually supports.

Creating a cause accepts `name`, `target_amount`, `priority` (integer, lower is higher priority), and `threshold_percent` (the percentage of target that must be reached before disbursements are allowed, defaults to 100). The cause returns an `id`, all provided fields, `allocated_amount`, `disbursed_amount`, and `status`.

Causes have these statuses:
- `OPEN` — accepting allocations
- `THRESHOLD_MET` — reached threshold percentage; disbursements now allowed
- `FUNDED` — reached 100% of target; no more allocations accepted
- `CLOSED` — manually closed; no more allocations; disbursements still allowed if funds exist

A cause's status transitions automatically based on `allocated_amount` relative to `target_amount`:
- When `allocated_amount` reaches `threshold_percent` of `target_amount`, status becomes `THRESHOLD_MET`
- When `allocated_amount` reaches `target_amount`, status becomes `FUNDED`
- If allocations are reversed (due to refund or grant revocation) and amount drops below the threshold, status reverts to `OPEN`
- If amount drops below 100% but stays above threshold, status reverts to `THRESHOLD_MET`

A cause can be manually closed, which sets status to `CLOSED`. Closed causes reject new allocations but allow disbursements. Closing is irreversible.

Cause priorities must be unique within a campaign. Lower priority numbers are higher priority (priority 1 is served before priority 2).


## Allocations

Allocations direct contribution funds to specific causes. Every dollar (including matched dollars) must be allocated to a cause before it can be disbursed.

Allocating funds accepts a `cause_id` and `amount`. The allocation is recorded in the contribution's `allocations` array as an object with `cause_id` and `amount`. The cause's `allocated_amount` increases. The campaign's `allocated_total` increases.

Allocation rules:
- Can only allocate from `CLEARED` contributions
- Can only allocate to `OPEN` or `THRESHOLD_MET` causes (not `FUNDED` or `CLOSED`)
- Cannot allocate more than the contribution's unallocated balance (which is `net_amount` plus `matched_amount` minus sum of existing allocations)
- Cannot allocate more than would exceed the cause's `target_amount`

When a contribution is refunded, all its allocations are automatically reversed: each cause's `allocated_amount` decreases by the allocation amount, and the campaign's `allocated_total` decreases accordingly.

When a grant is revoked, allocations funded by that grant's matches are proportionally reversed. If a contribution had $100 net plus $50 matched, and allocated $150 total across causes, revoking the grant removes the $50 in matches. The contribution's allocations are scaled down proportionally (each allocation reduced by 1/3 in this example), and cause allocated amounts decrease accordingly.


## Disbursements

Disbursements are the actual payouts to beneficiaries—the whole point of the campaign.

Creating a disbursement accepts `cause_id`, `beneficiary_name`, and `amount`. The disbursement returns an `id`, all provided fields, and `status`.

Disbursements have these statuses:
- `PENDING` — awaiting approval
- `APPROVED` — approved for payout
- `COMPLETED` — funds transferred
- `VOIDED` — cancelled

Disbursement eligibility (for creation):
- Campaign posture must be `OPEN` (not `RESTRICTED` or `FROZEN`)
- Cause status must allow disbursements: `THRESHOLD_MET`, `FUNDED`, or `CLOSED`
- Cannot disburse more than the cause's disbursable amount, which is `allocated_amount` minus `disbursed_amount` minus pending/approved disbursements for that cause
- Campaign must have sufficient `available_balance`

When a disbursement is created, the amount is reserved (reduces the cause's disbursable amount calculation).

Approving a disbursement transitions it from `PENDING` to `APPROVED`. Only `PENDING` disbursements can be approved.

Completing a disbursement transitions it from `APPROVED` to `COMPLETED`. The cause's `disbursed_amount` increases and the campaign's `disbursed_total` increases (which reduces `available_balance`). Only `APPROVED` disbursements can be completed. Campaign posture must be `OPEN`.

Voiding a disbursement transitions it to `VOIDED`. This can only be done on `PENDING` or `APPROVED` disbursements—once `COMPLETED`, it's too late. Voiding releases the reserved amount.

If cause allocations decrease (due to refund or grant revocation) below what's needed to cover pending and approved disbursements, those disbursements must be voided before the refund or revocation can complete. The system rejects the refund/revocation with an error indicating which disbursements need to be voided first.


## Holds

Holds are compliance mechanisms that restrict campaign operations when issues arise.

Creating a hold accepts `reason` and `severity` (either `STANDARD` or `CRITICAL`). The hold returns an `id`, the provided fields, and `status` of `ACTIVE`.

Holds have these statuses:
- `ACTIVE` — currently restricting the campaign
- `RESOLVED` — issue addressed; restrictions lifted

Campaign posture is derived from holds:
- If any hold has `severity` of `CRITICAL` and `status` of `ACTIVE`, posture is `FROZEN`
- Else if any hold has `severity` of `STANDARD` and `status` of `ACTIVE`, posture is `RESTRICTED`
- Otherwise, posture is `OPEN`

Resolving a hold transitions it to `RESOLVED` and recalculates campaign posture. Only `ACTIVE` holds can be resolved.

Multiple holds can exist simultaneously. The most severe active hold determines posture.


## Closing a Campaign

Campaigns can be closed to stop accepting new pledges and contributions while allowing final disbursements.

Closing a campaign sets its `phase` to `CLOSED`. Requirements:
- All pledges must be in terminal status (`FULFILLED`, `LAPSED`, or `VOIDED`)
- Campaign posture must be `OPEN`

Once closed:
- New pledges cannot be created
- New contributions cannot be created
- New grants cannot be created
- Existing grants cannot match new contributions (obviously)
- Allocations can still be made from existing contributions
- Disbursements can still be created, approved, and completed
- Causes can still be closed
- Holds can still be created and resolved

A closed campaign cannot be reopened.


## Error Precedence

When multiple error conditions apply, the system returns errors in this order:

1. `ERR_INVALID_REQUEST` — malformed request, missing required fields, invalid field values
2. `ERR_NOT_FOUND` — campaign or resource doesn't exist
3. `ERR_CAMPAIGN_CLOSED` — campaign is closed and operation requires active campaign
4. `ERR_POSTURE_FROZEN` — campaign posture is FROZEN
5. `ERR_POSTURE_RESTRICTED` — campaign posture is RESTRICTED
6. `ERR_INVALID_STATE` — resource is in wrong state for the operation
7. `ERR_PLEDGE_MISMATCH` — contribution amount doesn't match pledge
8. `ERR_INSUFFICIENT_FUNDS` — not enough available balance
9. `ERR_ALLOCATION_EXCEEDED` — allocation would exceed limits
10. `ERR_CAUSE_FULL` — cause has reached target amount
11. `ERR_DISBURSEMENT_BLOCKED` — disbursement blocked by pending disbursements needing void
12. `ERR_PLEDGES_OUTSTANDING` — cannot close campaign with outstanding pledges
13. `ERR_PRIORITY_CONFLICT` — cause priority already used


## Endpoints

| Method | Path |
|--------|------|
| POST | /campaigns |
| GET | /campaigns/:campaign_id |
| POST | /campaigns/:campaign_id/close |
| POST | /campaigns/:campaign_id/pledges |
| GET | /campaigns/:campaign_id/pledges/:pledge_id |
| POST | /campaigns/:campaign_id/pledges/:pledge_id/fulfill |
| POST | /campaigns/:campaign_id/pledges/:pledge_id/lapse |
| POST | /campaigns/:campaign_id/pledges/:pledge_id/void |
| POST | /campaigns/:campaign_id/contributions |
| GET | /campaigns/:campaign_id/contributions/:contribution_id |
| POST | /campaigns/:campaign_id/contributions/:contribution_id/refund |
| POST | /campaigns/:campaign_id/contributions/:contribution_id/allocate |
| POST | /campaigns/:campaign_id/grants |
| GET | /campaigns/:campaign_id/grants/:grant_id |
| POST | /campaigns/:campaign_id/grants/:grant_id/suspend |
| POST | /campaigns/:campaign_id/grants/:grant_id/reactivate |
| POST | /campaigns/:campaign_id/grants/:grant_id/revoke |
| POST | /campaigns/:campaign_id/causes |
| GET | /campaigns/:campaign_id/causes/:cause_id |
| POST | /campaigns/:campaign_id/causes/:cause_id/close |
| POST | /campaigns/:campaign_id/disbursements |
| GET | /campaigns/:campaign_id/disbursements/:disbursement_id |
| POST | /campaigns/:campaign_id/disbursements/:disbursement_id/approve |
| POST | /campaigns/:campaign_id/disbursements/:disbursement_id/complete |
| POST | /campaigns/:campaign_id/disbursements/:disbursement_id/void |
| POST | /campaigns/:campaign_id/holds |
| GET | /campaigns/:campaign_id/holds/:hold_id |
| POST | /campaigns/:campaign_id/holds/:hold_id/resolve |


## Response Envelope

All responses follow a standard envelope:

```json
{
  "response_type": "object | array | error",
  "data": { ... }
}
```

Error responses include `error_code` and `message` in the data payload.


## Error Codes

- `ERR_INVALID_REQUEST`
- `ERR_NOT_FOUND`
- `ERR_CAMPAIGN_CLOSED`
- `ERR_POSTURE_FROZEN`
- `ERR_POSTURE_RESTRICTED`
- `ERR_INVALID_STATE`
- `ERR_PLEDGE_MISMATCH`
- `ERR_INSUFFICIENT_FUNDS`
- `ERR_ALLOCATION_EXCEEDED`
- `ERR_CAUSE_FULL`
- `ERR_DISBURSEMENT_BLOCKED`
- `ERR_PLEDGES_OUTSTANDING`
- `ERR_PRIORITY_CONFLICT`