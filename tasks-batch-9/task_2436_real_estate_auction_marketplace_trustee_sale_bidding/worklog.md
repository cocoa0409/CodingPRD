# Worklog — task_2436_real_estate_auction_marketplace_trustee_sale_bidding

## Step 1: Create task directory — 2026-09-02T16:20:07.192Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2436_real_estate_auction_marketplace_trustee_sale_bidding/` and its `workspace/` subdirectory. Index 2436 was pre-assigned by the orchestrating caller (no scan/allocation performed, per instruction, to avoid collision with the up-to-32 concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-02T17:58:33.768Z

All three artifacts are complete and the task directory lints clean.

## Deliverables

- `/home/ubuntu/github/CodingPRD/tasks/task_2436_real_estate_auction_marketplace_trustee_sale_bidding/SCAFFOLD.yaml` (§1.0–§1.7, no design keys)
- `.../SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `.../SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

## Counts

| Table | Count |
|---|---|
| §1.1 entities | 11 (Seller, AssetListing, TrusteeSale, AuctionEvent, AuctionLot, Bidder, EligibilityExclusion, DepositHold, Bid, SaleContract, SecondChanceOffer) |
| §1.2 state machines | 7 (AssetListing is dual-axis: `listing_status` + `title_clearance_status`) |
| §1.2.1 OCC rules | 2 (`lot-add-stale-event`, `reserve-price-stale-lot`) |
| §1.3 calculations | 15 (2 dual-variant: `buyer_premium`, `bidder_risk_score`) |
| §1.4 validations | 56, strictly priority-ordered |
| §1.5 endpoints | 50 (27 writes + 23 reads incl. the logical-clock driver) |
| §1.6 errors | 56 |
| §1.7 roles | 8 (2 `entity_backed`: Seller, Bidder) |
| §1.8 instances | 18 — exactly 2 per each of the 9 rule_ids |
| §1.9 instances | 78 across all 9 taxonomy sections (69 full recipes + 9 `excluded_because` stubs) |

§1.9 section split: entities 11, state_machines 16, calculations 16, validations 12, endpoints 6, errors 7, rbac 4, cross_cutting_complexity_layers 5, consistency_model 1.

Verified independently of lint: all 56 error ids are triggered by at least one recipe; all 50 §1.5 endpoints are exercised by at least one real call; all 8 roles act; every stub's `difficulty_instance` resolves to a real §1.8 instance name; no duplicate instance names across the two design files; no forbidden concurrency vocabulary; every prose `assert` path/query-param matches a declared endpoint.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    50
  §1.1 entities declared:     11
  §1.8 instances scanned:     18
  §1.9 instances scanned:     69
  Calls scanned (§1.8+§1.9):  1175

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Design adjudications

- **Validation 29 narrowed to `registration_status != SUSPENDED`.** Requiring `== REGISTERED` made ERR_IDENTITY_UNVERIFIED (34) and ERR_BIDDER_BARRED (35) unreachable on the bids path, since REGISTERED implies VERIFIED. The rule now carries an explicit comment, and ERR_BIDDER_NOT_REGISTERED's catalog condition was rewritten to match.
- **`closing_deadline_at = closed_at + closing_window_days`**, not execution_at — 7 asserts across both design files that claimed `2026-10-06T18:10:00Z` were corrected to `18:05:00Z` (lot close time).
- **`POST /auction-events/{id}/lots` returns AuctionLot, not AuctionEvent.** Three recipes were capturing `$.data.version` from that response and replaying it as `expected_auction_event_version`; they now re-read the event via `GET /auction-events/{id}` between adds. (Left intact the recipes where the reuse is correct because the intervening add was rejected and therefore consumed no version.)
- **Offer decision enum unified to `ACCEPTED` / `DECLINED`** (§1.2 triggers said `ACCEPT`/`DECLINE` while §1.5 side effects and the entity status used the -ED forms).
- Dual-axis AssetListing + cyclic AuctionEvent (`SCHEDULED → LIVE → POSTPONED → SCHEDULED`) supply the non-linear state machines; reschedule leaves suspended lots SUSPENDED→PENDING with shifted windows rather than reopening them.
- County-scoped (not ALL-scoped) exclusion chosen for the priority-pair instance so the exclusion does not suspend the registration and mask the pair.
- Paired closed interval (`county_slot_overlap`, 30-minute buffer) against half-open interval (`lot_window_overlap`, per asset) to make the boundary semantics separately observable.
- Second-chance offers require only `lot_status == CLOSED_SOLD`, but ACCEPT additionally requires `listing_status == RELIST_PENDING`, so the accept path is only reachable after fallout — covered by a dedicated instance.
- Negative triggers are signalled with `captures: { err_id: $.data.error_id }` on clean real paths (no `_rejected`-style path suffixes, which the lint's template matcher rejects).

## Step 3: Copy shared files — 2026-09-02T17:58:55.317Z

Copied `./INSTRUCTION.md` → `tasks/task_2436_real_estate_auction_marketplace_trustee_sale_bidding/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-02T18:17:05.356Z

PRD complete and verified.

## Deliverable
`/home/ubuntu/github/CodingPRD/tasks/task_2436_real_estate_auction_marketplace_trustee_sale_bidding/workspace/PRD.md`

- **Final line count: 524**
- **Last section heading: `## 5. Error Code Catalogue`** (file ends on its final table row `| \`ERR_STALE_LOT_VERSION\` | 412 |` — a real section boundary, no mid-sentence truncation, no audit footer in the file)
- Written in 4 append passes; structure: §1 Introduction, §2.1–§2.12, §3.1–§3.8, §4, §5.
- The two withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced.

## Contract 1 — Field-Name Coverage: PASS
126/126 distinct names (entity fields + request-body inputs + query params + path params + computed-projection output keys) appear verbatim in backticks. 0 missing. Second pass over enum members / state names / constant values: all 7 state machines' state labels ticked (0 missing); every constant value present in prose (e.g. `DEPOSIT_PCT` as "five percent", floor 500000, multipliers 1.50/1.25/1.00/1.50, premium tiers 10000000/50000000 with 0.10/0.08/0.06, occupancy bps 150/100/0/200, title bps 0/75/175/250, 250000/6000000 clamps, 95000, 25000000/50000000 with 0.40/0.25, 35 bps, 45000, 25 bps carry, 6000 bps forfeiture, 60/120/3 extension seconds, 30-minute county buffer, 30-day hold extension, 72-hour offer window).

## Contract 2 — Rule Coverage: PASS
- 56/56 validations: §2.9 renders the ladder as rungs numbered 1–56, strictly ascending, priority→error id matching the scaffold exactly (0 mismatches), and all **113** `applies_to` endpoint mentions are co-located in the same paragraph as their error id.
- 56/56 error ids present.
- 51/51 state-machine transitions: every `from → to` pair co-occurs in a single paragraph (0 unpaired), including multi-source transitions.
- 15/15 calculations described with formula-in-prose, rounding order and input-set scoping; both OCC rules (`expected_auction_event_version`, `expected_auction_lot_version`, 412s) in §2.7; the five-link postponement cascade and its cancellation sibling in §2.11/§3.2; the two conservation identities and per-component-vs-per-rate-sum rounding in §2.8.
- §2.2 is byte-identical to `section-2.2-response-structure.md`.

## Contract 3 — §3 Path Purity: PASS
0 violations in §3 (lines 241–407): no backticked token beginning with `/`, no bare `GET/POST/PATCH/PUT/DELETE`, no method+path combos, and no code fences.

## Table conformance
§4: exactly 4 columns, **50 rows**, in scaffold order, with method, path and authorized-role lists matching the scaffold one-for-one. §5: exactly 2 columns, **56 rows**, ids and statuses matching the scaffold one-for-one.

## Scaffold inconsistencies resolved (decisions baked into the prose)
1. **Settlement posting timing** — endpoint side effects post `settlement_status`/`settled_net_cents` at execution; the state machine and field description say close. Chose execution-time posting (only coherent reading for the fallout branch that voids `POSTED` and reverses `seller_net_cents`); §3.7 states explicitly that escrow closing changes neither.
2. **`closing_deadline_at`** — endpoint says `closed_at + closing_window_days`; the field description and the input description say from execution. Chose `execution_at + closing_window_days`.
3. **Bid status at placement** — endpoint side effects say `WINNING`; the `bid_status` field default is `ACTIVE`. Chose `ACTIVE` at placement, predecessor `ACTIVE → OUTBID`, `WINNING` only at close or an accepted offer.
4. **Second-chance acceptance** — scaffold sets the offered bidder's bid to `WINNING` without demoting the incumbent; §3.8 demotes the previous `WINNING` to `OUTBID` to preserve `winning_bidder_id`'s "exactly one such bid" invariant.
5. **Event reschedule** — shifts every non-terminal lot; `SUSPENDED` lots stay `SUSPENDED` (no `SUSPENDED → PENDING` transition exists); holds untouched.
6. **`HOLD_INITIAL_DAYS`** has no declared value — described as "the hold's creation instant advanced by the platform's initial hold period" rather than inventing a number.
7. **Provisional premium on a lot with no hammer price** — reads 0, matching the settlement-preview rule.
8. Two conditions with no dedicated error (`PRIOR_FALLOUT` supplied by a client POST; reschedule `new_starts_at` not after the clock) mapped to `ERR_INVALID_REQUEST`.
9. **Doc-fee circularity** — pinned to the three-step order with the explicit note that `total_due_cents` may land below the tier floor that granted its discount, and that the tier is never re-keyed.

Orchestrator truncation-guard verification (independent of the subagent's own report): `wc -l` = 524; heading scan shows §1, §2.1–§2.12, §3.1–§3.8, §4, §5 all present in order; tail is the last row of the §5 table (a real section boundary, not mid-sentence); §5 has 56 `ERR_` rows and §4 has 50 data rows; `grep -ic 'harder than expert|difficulty'` = 0, so the Step 2-only difficulty instruction did not leak into the PRD. No regeneration needed.

## Step 6: Generate implementation — 2026-09-02T18:47:12.000Z

(Steps 5 and 6 were launched concurrently in a single assistant message, per the skill's physical-isolation requirement. Step 6 returned first, so its entry is recorded here ahead of Step 5's; the launch order was simultaneous.)

The implementation is complete and verified end-to-end.

## Deliverable
`/home/ubuntu/github/CodingPRD/tasks/task_2436_real_estate_auction_marketplace_trustee_sale_bidding/workspace/implementation/`

| File | Role |
|---|---|
| `start.sh` (executable), `requirements.txt`, `app.py` | launcher (guarded pip install, then `exec python3 app.py`), `flask>=3.0`, `create_app()` + envelope error handlers for `ApiError` / `HTTPException` / unexpected exceptions |
| `db.py` | in-memory `Store` (11 dicts keyed by id), logical clock defaulting to `2026-08-01T00:00:00Z`, id/version/`_seq` helpers, deterministic `ordered()` |
| `errors.py` | all 56 error ids → HTTP status, `ApiError` |
| `util.py`, `serial.py`, `validate.py`, `auth.py` | envelope + ms-precision timestamps, per-entity field projections, body/query coercion, `X-User-ID`/`X-User-Role` with 8 roles and ownership checks |
| `calc.py` | eviction tier, required deposit, tiered buyer premium, contract price, doc fee, settlement + forfeiture splits (integer cents via `Decimal` ROUND_HALF_UP) |
| `services.py` | shared domain layer: ledger/screen-score recompute, risk assessment (SCREEN + AUDIT), county-slot vs lot-window geometries, hold lifecycle, postponement/cancellation cascades, event bubble-up close, barring, second-chance eligibility |
| `helpers.py` | FK resolution (absent → rung 14; unresolvable → declared 404) |
| `routes/` | `sellers.py`, `listings.py`, `trustee.py`, `events.py`, `lots.py`, `bidders.py`, `contracts.py`, `clock.py`, `__init__.py` |

2,713 lines of Python. No `__pycache__` left behind; grep confirms zero `sqlite`/`pickle`/`open(`/`json.dump`/`/tmp` usage — storage is purely process-local dicts, nothing is seeded at import time.

## Endpoints
Diffed `app.url_map` against `SCAFFOLD.yaml`: all **50 declared endpoints** present (only the URL parameter name differs, `<rec_id>` vs `{id}`), plus `POST /_clock/set_current_utc` and Flask's default `/static/<filename>`.

## Verification
- Happy-path smoke suite (`/tmp/smoke2436.py`): seller → asset → disclosures → trustee sale → confirm → event/lot → OCC 412s → county-slot adjacency 409 → lot-window 409 → bidder registration/KYC/funding → open → bidding (below-minimum 422, outbid hold release, self-raise hold reuse, late-bid extension) → close (`CLOSED_SOLD`, provisional premium 1,760,000, sale `HELD`, event `CLOSED`) → title clearance → segregation-of-duties 403 → contract (price 22,000,000, final premium 2,145,000, doc fee 95,000, platform fee 1,222,000, conservation identity holds, `closing_deadline_at 2026-09-22T17:32:00.000Z`) → fallout (forfeiture 1,000,000 → 600,000/400,000) → second-chance offer/accept → second contract → escrow close → auth/404/pagination/assessment. **0 failures.**
- Cascade smoke suite (`/tmp/smoke2436b.py`): 3-cycle postpone/reschedule/reopen loop verifying the 5-link postponement chain (sale `POSTPONED`, event `POSTPONED`, lot `SUSPENDED`, hold `EXTENDED` with clock+30d expiry, ledger untouched and no spurious bidder version bump), the extension-limit release at count 3 (`RELEASED`/`EXTENSION_LIMIT`, bid `WITHDRAWN`, deposit freed), reschedule window shifting (+1 day, `bid_close_at` = shifted end, `extension_count` reset, SUSPENDED preserved), cancellation cascade (event `CANCELLED`, lot `WITHDRAWN`, asset `UNSOLD`, second cancel 409, freed county slot reusable), relist, no-sale close (`CLOSED_NO_SALE`, hold `NO_SALE`, below-reserve bid stays `ACTIVE`, event `CLOSED`, second-chance 409), and exclusion create/suspend/lift/reinstate plus AUDIT-mode historical reconstruction. **0 failures.**
- Real launcher path over HTTP: `PORT=10099 bash start.sh` binds `0.0.0.0`, responds in under 4s in the foreground; curl checks confirmed the envelope, the clock endpoint, `ERR_SELLER_NOT_FOUND`, seller creation, and — after kill + relaunch — an empty store and the clock back at `2026-08-01T00:00:00Z`, which is exactly the `--isolation per-test-server` contract.

## PRD ambiguities resolved
1. `HOLD_INITIAL_DAYS` never pinned numerically → **30 days** (documented in `calc.py`).
2. Bid acceptance sets `bid_status = ACTIVE` (PRD §3.5) rather than the scaffold's `WINNING`; prior ACTIVE → OUTBID; `WINNING` only at close or on an accepted second-chance offer.
3. Rungs 40/41 on sale-contract: title `PENDING` → `ERR_TITLE_CLEARANCE_PENDING`, `DEFECTIVE` → `ERR_TITLE_DEFECTIVE` (per SCAFFOLD §1.6 conditions).
4. Self-raise (displaced bidder == incoming bidder): the live hold is reused, not released/re-created; rung 56 is skipped when a HELD/EXTENDED hold already exists on that lot.
5. Reschedule keeps SUSPENDED lots SUSPENDED (PRD §3.3 over the scaffold's "set to PENDING"); windows shift by the start delta, all conflicts are checked before any commit.
6. `buyer_premium` returns 0 for price <= 0, so `settlement-preview` reads all zeros before a lot closes.
7. Absent body FK → rung 14 `ERR_INVALID_REQUEST`; present but unresolvable → its declared 404.
8. `POST /auction-lots/{id}/bids` is absent from rung 8's `applies_to`, so ordering is ownership → `ERR_BIDDER_NOT_FOUND` → rung 14.
9. `GET /bidders/{id}/eligibility-assessment` with an unresolvable `auction_lot_id` → `ERR_AUCTION_LOT_NOT_FOUND` after rung 16.
10. `settlement_status = POSTED` at execution; `closing_deadline_at = execution_at + closing_window_days` (PRD) rather than the scaffold's `closed_at`.
11. Version bumps: single forced bump for endpoint-declared bidder recomputes; change-based bumps inside cascades.
12. Assessment `*_applied` fields report raw pre-cap contributions; `risk_score = min(100, sum)`; `eligible = risk_score < 40`. AUDIT mode counts exclusions effective at or before `event.starts_at` that were still active then (including ones lifted afterwards).
13. Second-chance acceptance promotes the offered bidder's highest OUTBID bid (amount desc, then created_at, `_seq`) to WINNING.
14. Unknown route / 405 → JSON envelope with `ERR_INVALID_REQUEST` at the original status.
15. `GET /deposit-holds/{id}` has no declared 404 → `ERR_DEPOSIT_HOLD_NOT_FOUND` at HTTP 404.
16. `AuctionEvent.lot_count` stored and recomputed; `Seller.settled_net_cents` moves on execution (+seller_net) and fallout (−seller_net, +forfeiture seller net); escrow close does not re-post.
17. Reinstatement after a lift re-evaluates only ACTIVE, ALL-scoped, already-effective exclusions.

## Step 5: Generate unit tests — 2026-09-02T20:03:40.000Z

(Recorded after Step 6's entry because Step 6's concurrently-launched subagent returned first; both were launched simultaneously in one assistant message.)

Generation is complete. All of queue A and queue B have been translated.

## Files written

Under `/home/ubuntu/github/CodingPRD/tasks/task_2436_real_estate_auction_marketplace_trustee_sale_bidding/`:

**`test_helpers/`** (infrastructure): `__init__.py` (barrel), `constants.py`, `types.py`, `test_users.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `fixtures.py`.

**`test_suite/`** (`conftest.py` + 18 test modules, 7,450 lines):
- Queue A (§1.8): `test_01_dual_variant_calc.py`, `test_02_combinatorial_formula.py`, `test_03_non_linear_state_machine.py`, `test_04_transitive_cascade.py`, `test_05_priority_pair_validation_conflict.py`, `test_06_boundary_precision_check.py`, `test_07_cross_entity_state_dependency.py`, `test_08_resource_temporal_overlap.py`, `test_09_compensating_invariant.py`
- Queue B (§1.9): `test_10_entities.py`, `test_11_state_machines.py`, `test_12_calculations.py`, `test_13_validations.py`, `test_14_endpoints.py`, `test_15_errors.py`, `test_16_rbac.py`, `test_17_optimistic_concurrency.py`, `test_18_consistency_model.py`

## Counts

- **119 tests collected.** Queue A: **51 tests** over **18/18** non-stub difficulty instances (>=2 tests each). Queue B: **68 tests** over **68/69** non-stub corner instances (>=1 each).
- Every test carries exactly one trailing `Design:` line; audit reports no untagged, dual-tagged, unresolved or stub-pointing tags. 167 `PRD:` citations, all literal (`non_literal=0`). Zero occurrences of "scaffold" in `test_suite/`.
- pyflakes clean across the suite; every `from test_helpers import` name and every `api_client.<method>` reference resolves.

## Instances skipped

- `Corner/validations/lot_county_must_match_its_event_county` — no PRD rule supports it. `ERR_COUNTY_MISMATCH` is scoped in §2.9 to `POST /trustee-sales` only; the lot-admission rule set (PRD line 293) never compares the asset's `county_code` to the event's. Gap left as a gap.
- All `excluded_because:` stubs, per spec: 1 in `state_machines`, 2 in `validations`, 3 in `cross_cutting_complexity_layers`.

## Adjudications (design asserted X, PRD uniquely derives Y — emitted Y)

1. `contract_close_releases_hold_and_seals_the_listing` — `closing_deadline_at` is `2026-10-06T18:10:00Z` (execution instant + 21 days), not the design's 18:05.
2. `no_sale_close_releases_holds_but_sold_close_retains_them` — a below-reserve standing bid stays `ACTIVE` (PRD line 356), not `OUTBID`.
3. `backup_pool_excludes_suspended_bidder_until_exclusion_is_lifted` — exclusion recorded at 17:25 so it is in force; dropped a non-derivable flag assertion.
4. `deposit_exactly_equal_to_requirement_passes_one_cent_short_fails` — `ERR_DEPOSIT_INSUFFICIENT` is 402, not 422.
5. `postponements_are_capped_by_the_statutory_maximum` — re-confirm between postponements; 409, not 422; dropped an unreachable terminal-status assertion.
6. `segregation_of_duties_only_bites_when_the_same_user_acts_twice` — 403, not 409.
7. `closing_after_the_deadline_is_refused_but_fallout_is_still_allowed` — deadline 18:10, not 18:05.
8. `every_declared_read_channel_answers_for_one_completed_auction` — hold expiry 18:10; trustee sale reads `HELD` after a sold close (PRD line 354), not `CONFIRMED`.
9. `unverified_and_suspended_bidders_hit_different_gates` — exclusion must be recorded after the clock reaches its `effective_at`, or PRD line 323 never suspends the bidder.
10. `intake_write_endpoints_admit_only_their_owning_role` — occupancy `TENANT_OCCUPIED`; the design's `TENANT` is not in the enum.
11. `bidder_writes_are_scoped_to_the_acting_bidder_id` — a fresh bid is `ACTIVE`; `WINNING` arrives only at close or via an accepted second-chance offer (PRD line 342).
12. `sellers_cannot_reach_each_others_listings` — a fresh intake reads `occupancy_status == "UNKNOWN"` (PRD line 251), not null.
13. `one_bid_makes_every_derived_row_visible_in_the_same_request` — same `ACTIVE`-not-`WINNING` correction for the raising bid.

Note: the suite has been verified statically and by collection only. No end-to-end run was performed, since the only server implementation lives under `workspace/implementation/`, which I was instructed not to touch while a concurrent subagent generates it.

## Step 7: Run tests and iterate — 2026-09-02T20:14:40.270Z

All 8 fresh results files confirm 119/119.

## Summary

**Iterations run:** 2 (one diagnostic sweep, one verification sweep). Final sweep: all 8 parallel rounds **119/119 passed**, verified by reading all 8 `results.$i.json` (all written at 20:04:30, same sweep).

**Iteration 1 failures** — 4 tests, failing identically in all 8 rounds (fully deterministic, no flakiness):

**Tests deleted:** none. Every failure traced to a test-side bug (STEP 2), not PRD silence.

**Fixes applied to `test_helpers/`:**
- `test_helpers/assertions.py` — `assert_timestamp_equals()`: it normalized only the *actual* side (`.000Z` → `Z`) and not the *expected* side, so comparing two PRD-conformant serialized timestamps against each other failed with the absurd message `expected 2026-08-05T00:00:00.000Z, got 2026-08-05T00:00:00.000Z`. Now normalizes both sides. This fixed `test_a_second_disclosure_filing_is_refused_and_overwrites_nothing` (test_11), which passes a server-returned `disclosure_ack_at` as the expected value.

**Fixes applied to `test_suite/`:**
- `test_18_consistency_model.py` — `test_one_outbidding_call_leaves_every_derived_row_already_settled`: raw string equality `raising["placed_at"] == CLOCK_SECOND_BID` (and `lot["bid_close_at"] == LOT_WINDOW_END`) compared a PRD-mandated three-fractional-digit serialization against a plain `...Z` constant. PRD §2.6 requires `created_at`/`updated_at`/`*_at` "serialized as an ISO 8601 UTC timestamp with three fractional digits, for example `2026-08-01T00:00:00.000Z`", so the implementation was right. Switched both to `assert_timestamp_equals` (imported it).
- `test_07_cross_entity_state_dependency.py` — `test_execution_succeeds_and_prices_the_contract_once_title_is_cleared`: asserted `listing["verified_title_condition"] == "CLEAR"` (KeyError). PRD §3.1 names `verified_title_condition` only as a *title-clearance request input* — "`verified_title_condition`, the officer's finding, which overwrites the seller's `title_condition` outright" — never as a response-visible `AssetListing` attribute. Retargeted the assertion to the PRD-named stored field, `listing["title_condition"] == "CLEAR"`, which is the verbatim-derivable outcome (kept, not weakened).
- `test_10_entities.py` — `test_bidder_system_fields_are_server_minted_and_version_starts_at_one`: asserted `verified["updated_at"] != created["updated_at"]` with the logical clock frozen at `CLOCK_SETUP` across both calls. PRD §2.5/§2.6 make `updated_at` the *logical-clock* instant of the last mutation and forbid wall-clock reads, so the two values must be equal — the test contradicted the PRD. Made it faithful by advancing the clock to `2026-08-06T00:00:00Z` before the verification call, and strengthened it: `created_at` must still read `CLOCK_SETUP`, while `identity_verified_at` and `updated_at` must both read the new instant.

**Fixes applied to `implementation/`:** none — no implementation defect was found. All four failures were test-artifact bugs (a broken assertion helper, two raw-string timestamp comparisons, one input-field-vs-stored-field name confusion, and one wall-clock assumption in a logical-clock system).

Orchestrator verification (independent of the subagent's report, per the known failure mode where a Step 7 agent claims a clean sweep with no artifacts on disk): `ls -l results.*.json` shows all 8 files present with mtime 20:04, and parsing each one gives `passed=119 total=119 failed=0` for rounds 1–8. Sweep confirmed genuinely clean.

Step 8 gating decision: Step 7 applied 3 `test_suite/` fixes and 1 `test_helpers/` fix (0 deletions, 0 `implementation/` fixes), so the skip condition (zero iterations beyond baseline) does NOT hold — Step 8 runs. Note for Step 8's scope: since there were no implementation fixes, the PRD-silence signals here are the test-side corrections, chiefly the `verified_title_condition` input-vs-stored-field distinction and the timestamp-serialization/logical-clock `updated_at` semantics.

## Step 8: Finalize PRD — 2026-09-02T20:28:00.000Z

`PRD_FINALIZED.md` written at `/home/ubuntu/github/CodingPRD/tasks/task_2436_real_estate_auction_marketplace_trustee_sale_bidding/workspace/PRD_FINALIZED.md`.

## Size
PRD.md 524 lines → PRD_FINALIZED.md 526 lines (+2 lines, +0.38%). Two edits total.

## Changes
- **§2.6 — insert** — added one sentence pinning that every stored `*_at` field (not just `created_at`/`updated_at`) is serialized as an ISO-8601 UTC timestamp with three fractional digits, and reads `null` while unset — `implementation/serial.py:72-84` (`_value` → `fmt_dt` for every `datetime`), `implementation/util.py:19-27` (`fmt_dt`).
- **§3.1 — revise** — added a clause to the title-work paragraph pinning that `verified_title_condition` and `title_report_reference` are request inputs only; the finding is recorded solely by overwriting `title_condition` and neither appears as an asset-listing attribute — `implementation/routes/listings.py:94-100`, `implementation/serial.py:14-19`.

## Per-edit pre-edit search log

**Edit 1 (§2.6, timestamp serialization)**
- (a) Subject: the wire format of every timestamp-valued field on every resource, and the unset case.
- (b) Paths enumerated: `serial.py:7-69` (full field lists for all 11 entity kinds — extracted the complete set of `*_at` fields), `serial.py:72-84` (`_value`/`dump`/`dump_many` — the single serialization funnel; keys are always emitted, `None` → `null`), `util.py:19-27` (`fmt_dt`, always exactly 3 digits; `None` → `None`), `util.py:35-48` (`parse_dt`/`trunc_ms` — client-supplied instants are stored as `datetime`, not strings), `validate.py:102-114` (`req_dt`/`opt_dt` return parsed `datetime`s), `db.py:61-78` (`created_at`/`updated_at`/`touch` from the logical clock), plus a repo-wide grep of every `*_at` assignment (`services.py:299,319,403,405`; `routes/events.py:38-42,91-104,133,172-181`; `routes/listings.py:62,81`; `routes/contracts.py:72-87,99,117,145,225,227,266`; `routes/lots.py:98,106,139`; `routes/bidders.py:32,58,103,105,125`; `routes/trustee.py:40,83`) — every one stores a `datetime`, so no field escapes `fmt_dt`. Also checked the two computed projections (`routes/lots.py:222-239` settlement-preview, `routes/bidders.py:163-181` + `services.risk_assessment`) — neither returns any timestamp, so the sentence cannot mis-describe them; and `util.py:78-82` (`api_request_timestamp`, already pinned by §2.2, same helper).
- (c) Wording adjustments: scoped the claim to fields "the system stores on a resource" so it makes no claim about the projections or `meta`; wrote "in that same three-fractional-digit form" rather than restating precision rules, so it stays silent about sub-millisecond client input (which `parse_dt` truncates) instead of asserting a rounding/truncation rule Step 7 never exercised; added "whether the server stamped it … or the client supplied it" because `starts_at`/`effective_at`/`expires_at` come from request bodies; qualified the null clause as "for as long as it is unset" rather than a blanket nullable claim, since `effective_at`, `sale_scheduled_at` and an offer's `expires_at` are never null.

**Edit 2 (§3.1, title-clearance inputs)**
- (a) Subject: what the title-clearance request's two non-outcome inputs do to the `AssetListing` row and its response shape.
- (b) Paths enumerated: `routes/listings.py:88-110` (`record_title_clearance`: `verified` and `title_report_reference` are validated then only `asset["title_condition"] = verified`; the reference is discarded), `serial.py:14-19` (asset_listing field list — neither name present, so all four asset-listing reads in §4 omit them), and every consumer of the finding to confirm it is reachable only via `title_condition`: `calc.py:120-124` (`eviction_risk_tier`), `calc.py:150-157` (`buyer_premium` title surcharge), `calc.py:195-199` (title service fee), `services.py:274` (provisional premium refresh), `routes/lots.py:147,255,260` (close + settlement preview), `routes/contracts.py:55,60` (final premium + settlement at execution), `routes/listings.py:56,75-82` (intake default and seller disclosure writing the same field), `routes/listings.py:113-129` (relist resets `title_clearance_status` but leaves `title_condition` standing).
- (c) Wording adjustments: said "recorded solely by overwriting `title_condition`" instead of "not stored", so the sentence does not imply the finding is lost — it is durable, and the relist path keeps it; added "or appears in the asset listing responses of §4" to cover the read endpoints without introducing a new field list; deliberately made no claim about whether a later relist or disclosure re-writes the value, since those paths are outside the edit's assertion.

## Step 7 items that produced no edit
- `test_helpers/assertions.py` `assert_timestamp_equals` normalization bug — pure helper artifact; the underlying behavior (three-digit `disclosure_ack_at`) is now pinned by Edit 1, so no separate change.
- `test_10_entities.py` `updated_at` wall-clock assumption — PRD §2.5/§2.6 already uniquely determine that `updated_at` and `identity_verified_at` read the logical clock and that `created_at` is untouched; `implementation/db.py:74-78` and `routes/bidders.py:56-65` match the existing prose verbatim. No silence, no mismatch, prose kept as-is.
- `test_18_consistency_model.py` raw-string timestamp comparisons — same root cause as Edit 1; no additional prose needed.
- Zero implementation fixes in Step 7, so no PRD/impl divergence to reconcile anywhere else.

## Step 9: Complete PRD — 2026-09-02T20:45:57.192Z

**Deliverable:** `/home/ubuntu/github/CodingPRD/tasks/task_2436_real_estate_auction_marketplace_trustee_sale_bidding/workspace/PRD_COMPLETED.md`

**Size:** source `PRD_FINALIZED.md` 526 lines / 101,704 chars → `PRD_COMPLETED.md` 528 lines / 108,838 chars (**+2 lines, +7,134 chars**). 28 hunks: 26 in-place line revisions + 2 pure insertions (`84a85` error-envelope bullet, `483a485` §5 table row). No new sections; every change is an in-paragraph insert or revision.

**Counts:** 22 ambiguity-pins, 6 mismatch-revisions.

**Changes**
- §2.2 — revise — ambiguity — `api_request_timestamp` reads the logical clock, not wall time — util.py:78-82
- §2.2 — insert — ambiguity — unrouted path / unsupported method answer in the error envelope as `ERR_INVALID_REQUEST` with HTTP 404/405 — app.py:30-34
- §2.3 — insert — ambiguity — equal `created_at` ties break by server minting (insertion) order, making ordering total — db.py:81-87
- §2.4 — insert — ambiguity — filters exact and case-sensitive; unresolvable value matches nothing; empty value treated as absent; non-member enum is `ERR_INVALID_REQUEST` — validate.py:147-160
- §2.5 — insert — ambiguity — the clock may be set backwards as freely as forwards — clock.py:13-21
- §2.6 — insert — ambiguity — inbound instants normalized to UTC and truncated (never rounded) to whole milliseconds — util.py:30-48
- §2.6 — insert — ambiguity — a no-op recomputation is not a mutation; four bidder-directed writes are forced exceptions — services.py:96-103, bidders.py:65,81,113,135
- §2.9 rung 8 — insert — ambiguity — bids' body `bidder_id` resolves on rung 8, but rung 13 ownership settles first — lots.py:44-50
- §2.9 rung 12 — insert — mismatch — `GET /deposit-holds/{id}` resolves here, answering `ERR_DEPOSIT_HOLD_NOT_FOUND` (404) — bidders.py:213-216
- §2.9 rung 14 — insert — ambiguity — undeclared fields ignored; absent/empty/unparseable body read as `{}`; non-object JSON rejected — validate.py:15-25
- §2.9 rung 16 — insert — ambiguity — supplied-but-unresolvable `auction_lot_id` is `ERR_AUCTION_LOT_NOT_FOUND`, checked after this rung — bidders.py:174-180
- §3.1 — insert — ambiguity — the uppercase 3–32-char `county_code` rule also governs trustee-sale and auction-event bodies — listings.py:19-23, trustee.py:26, events.py:26
- §3.2 — insert — ambiguity — `postponement_reason` is validated but not carried on the sale record — trustee.py:74
- §3.3 — insert — ambiguity — an event window is never compared to the clock, nor its county to the bound sale's or lotted assets' counties — events.py:20-46
- §3.3 — insert — ambiguity — reserve revision never examines `lot_status`; the bid-free test is the only state gate — lots.py:19-35
- §3.3 — revise — ambiguity — reschedule conflict check uses siblings' shifted windows; shifted windows are not re-checked against the event's new bounds — events.py:159-183, services.py:240-254
- §3.4 — revise — ambiguity — `deposit_available_cents` also starts at 0 — bidders.py:35
- §3.4 — insert — ambiguity — `document_reference` required but not carried on the bidder — bidders.py:52
- §3.4 — insert — ambiguity — `funding_reference` required but not carried on the bidder — bidders.py:76
- §3.4 — insert — ambiguity — exclusion `county_code` scope is any non-blank string, exact-equality compared — bidders.py:92-94
- §3.4 — revise — mismatch — lift `notes` replaces outright when supplied / untouched when omitted; lift is not gated on exclusion status — bidders.py:122-128
- §3.5 — insert — ambiguity — the initial deposit-hold period is thirty days — services.py:293-304, calc.py:65-70
- §3.5 — revise — mismatch — a bidder raising itself keeps its own hold encumbered instead of releasing it — lots.py:85-92
- §3.7 — insert — ambiguity — preview recomputes from current asset/seller/sale state, never reads an executed contract; `provisional_premium_cents` is the stored lot field; all money reads 0 while `hammer_price_cents` is 0 — lots.py:222-274
- §3.8 — insert — mismatch — offer issuance examines only `CLOSED_SOLD`; no contract need exist and one may still be `EXECUTED` — contracts.py:203-216
- §3.8 — revise — ambiguity — the accepting bidder's *highest* bid is promoted; the demoted winner's hold is neither released nor captured — contracts.py:275-310
- §4 — revise — mismatch — the "zero or one" sale-contract cardinality is not enforced — contracts.py:23-101
- §5 — insert — mismatch — added `| ERR_DEPOSIT_HOLD_NOT_FOUND | 404 |` after `ERR_BID_NOT_FOUND` — bidders.py:215

**Verification performed:** all 50 endpoints' authorized-role lists cross-checked against §4 (all match); every route's check sequence walked against the 56-rung ladder (exactly two local deviations found, both pinned); `errors.py` `ERROR_HTTP` confirmed to contain precisely the 56 IDs in §5, with `ERR_DEPOSIT_HOLD_NOT_FOUND` the sole extra runtime ID. Unreachable behaviors (equal-amount backup-bid ties, fallout with no live hold, `recompute_lot_count` no-op) were deliberately left unpinned to avoid bloat. `SCAFFOLD*.yaml` and `worklog.md` were never opened.

Orchestrator verification: `PRD_COMPLETED.md` is 528 lines / 108,838 chars, carries the same 28 headings as `PRD.md` (no section lost), ends at a real section boundary (final row of the §5 table), and the §5 catalogue now has 57 `ERR_` rows — the original 56 plus the newly documented `ERR_DEPOSIT_HOLD_NOT_FOUND`. Pipeline complete: Steps 1–9 all done, `workspace/PRD_COMPLETED.md` written.

---

## Pipeline complete — 2026-09-02T20:45:57.192Z

Final state of `tasks/task_2436_real_estate_auction_marketplace_trustee_sale_bidding/`:
- `SCAFFOLD.yaml` (3,017 lines), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1,769), `SCAFFOLD_CORNER_DESIGN.yaml` (5,045)
- `test_helpers/` (9 modules), `test_suite/` (conftest + 18 modules, 119 tests, 0 deleted)
- `workspace/INSTRUCTION.md`, `PRD.md` (524), `PRD_FINALIZED.md` (526), `PRD_COMPLETED.md` (528)
- `workspace/implementation/` — Python + Flask, 50 endpoints, in-memory only, `start.sh` launcher, `results.1.json` … `results.8.json` all at 119/119
