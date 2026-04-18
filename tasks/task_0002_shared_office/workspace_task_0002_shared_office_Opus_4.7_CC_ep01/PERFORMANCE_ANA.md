# Performance Analysis: workspace_task_0002_shared_office_Opus_4.7_CC_ep01

**Result: 118/123 (95.9%)**

## Root Causes

### 1. Nullable money fields at non-terminal / inapplicable states — 4 failures (80%)

The implementation initializes fee columns to `None` (rather than `0`) when a value has not yet been computed, and leaves them at `None` in terminal states where the PRD implies zero. The shape contract (PRD §2.9 "cents are non-negative integers", enforced by the test assertions as `isinstance(..., int) and ... >= 0`) demands an integer in every response. Concrete sites:

| Entity / state | Field left as `None` | Failing test |
|---|---|---|
| Lease `DRAFT` (routes/leases.py:48) | `termination_penalty_cents` | `test_create_draft_lease` |
| Reservation `PENDING` (routes/reservations.py:149) | `final_fee_cents` | `test_create_reservation_enters_pending` |
| Visitor `REGISTERED` (routes/visitors.py:81) | `overstay_fee_cents` | `test_register_visitor_enters_registered` |
| Reservation `CANCELLED` from `CONFIRMED` (routes/reservations.py:233–235 — clears only `provisional_fee_cents`) | `final_fee_cents` | `test_reservation_branching_to_three_terminals_primary` (`assert None == 0`) |

All four fail on the same kind of shape check; the last one is the loudest because it surfaces as a direct `None == 0` comparison rather than an `isinstance` assertion.

### 2. Error-precedence misclassification on reservation create — 1 failure

`routes/reservations.py:117–119` adds an "actor scope" guard (`actor.tenant_id != payload.tenant_id`) that raises `ERR_FORBIDDEN` **before** the cross-tenant referential check at line 125–126. For the scenario where member_a (tenant_a) submits a payload claiming `tenant_id = tenant_b`, PRD §3.3 explicitly pins the first applicable rule as `ERR_TENANT_MISMATCH` ("The request is evaluated first for the cross-tenant referential rule…"). The acting-member scoping and the member/payload-tenant mismatch collapse to the same observation and should surface as the business-safety error, not an RBAC denial. Failing test: `test_tenant_mismatch_when_member_belongs_to_other_tenant`.

## Model Weaknesses

**Tri-state "unset" conflation.** The model reaches for SQL-nullable semantics (`None` = "not yet computed") for money columns that the PRD treats as always-present non-negative integers. The three initialization sites and the one terminal-transition site all follow the same reflex. In a black-box regime where every response flows through a shape assertion, any nullable numeric field is a latent failure — an explicit zero default would have cost nothing and avoided four tests.

**Layered guard duplication crowding out contract errors.** The model defends the reservation endpoint with two near-identical tenant checks (actor-scope then cross-tenant) and picks the RBAC-shaped error for the first one. The PRD's global §2.8 precedence table plus the §3.3 "evaluated first" phrase pin a specific ordering that the extra guard subverts. This is a common failure mode when the model treats RBAC and domain referential integrity as interchangeable refusals.

## What Passed

All 118 other tests pass: auth/RBAC envelope, pagination, tenant/member CRUD, full lease lifecycle including SoD and termination cascades, resource CRUD, reservation temporal/granularity/capacity/overlap rules, the full reservation state machine (confirm, cancel, check-in, check-out, sweep→NO_SHOW), every provisional and final fee calculation (tier flip, weekend discount, tiebreak), visitor window and overstay fee logic, access badge lifecycle, bill lifecycle with tax sum-then-round and strict-floor overdue thresholds, access-posture flips, and 20 of 21 difficulty-coverage combos. The business logic and state machinery are essentially correct; the failures are interface-contract bugs at response-shape boundaries, not behavioural regressions.
