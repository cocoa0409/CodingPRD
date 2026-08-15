# Worklog — task_1337_restaurant_surplus_food_rescue_logistics

## Step 1: Create Task Directory — 2026-08-12T22:36:00.000Z

Task directory `tasks/task_1337_restaurant_surplus_food_rescue_logistics/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline invoker; treated as DONE per instructions. No index scan performed, no other task directory touched.

## Step 2: Generate Scaffold — 2026-08-12T23:54:00.000Z

Scaffold generation complete. All three artifacts are written and the mandatory lint passes clean.

## Deliverables (all under `/home/ubuntu/github/CodingPRD/tasks/task_1337_restaurant_surplus_food_rescue_logistics/`)

- **SCAFFOLD.yaml** — §1.0–§1.7 only (no design keys). 12 entities, 9 state machines, 11 calculations, 12 ordered validations, 33 endpoints, 36 error codes, 4 roles with `identity:` declarations, 2 OCC concurrency rules, fixed response envelope verbatim.
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml** — single key `scaffold_difficulty_design`; all 9 rules × 2 instances = 18, every one with fully structured `setup_api_calls`/`trigger` chains and pre-computed literal assertions.
- **SCAFFOLD_CORNER_DESIGN.yaml** — single key `scaffold_corner_design`; 39 active instances + 10 `excluded_because` stubs across all 9 claim-extraction-guide sections.

## Design shape (Expert+ per the directive)

- **Archetype**: quota/allocation (agency lbs, vehicle lbs, cooler liters, driver windows) × temporal windowing; layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, selector_policy. Flat topology, cyclic machines (offer re-offer loop, cooler checkout cycle, driver suspend/reinstate) plus a parallel-dimension `RescueRun` (`run_status` × `safety_status`), segregation-of-duties on strike adjudication.
- **Fiendish calculations**: danger-zone compliance with per-category danger bands, pickup kill screens (inclusive at 70.0°F/100.0°F), linear crossing interpolation and an inclusive 240-minute cumulative limit (480-min span → 240 COMPLIANT vs 482 → 241 VIOLATION); IRC-170(e)(3)-style enhanced tax valuation `min(2×basis, basis + round_half_up((fmv−basis)/2))` with per-lb-rate-then-multiply rounding pinned (1260 vs 1255 trap); estimated-vs-verified weight divergence; reliability scoring with cap/penalty/reset.
- **Density mechanics**: 6-deep adjudication→suspension→run-teardown cascade; capacity boundary at exactly-full (100 == 100 accepted, 101 rejected); buffered vs half-open overlap semantics on different resources; two OCC create-with-supersede races (dispatch on `DonationOffer.version`, receipt issuance on `DonorSite.version`); deterministic selectors with `created_at` tie-breaks (never `id`); logical-clock endpoint with the mandated `2026-08-01T00:00:00Z` default.

## Lint verdict (verbatim)

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
Coverage: 33 endpoints, 12 entities, 18 §1.8 instances, 39 active §1.9 instances, 972 calls scanned.

Additional manual audits beyond the linter: zero forbidden-vocabulary hits, 67 unique instance names across both design files, every `grounds:` ref resolves, all stubs cite existing §1.8 instances, all 36 error codes are both referenced and test-covered, enum-value closure verified for every state field.

One disclosed deviation: the endpoint count is **33**, one above the directive's 28–32 aim — the extra endpoint is the lint-mandated FK reverse-reachability surface for `CoolerReservation`/`StrikeReport` (sub-resource GETs under `/api/rescue-runs/{id}/` and `/api/coolers/{id}/`); the scaffold header notes this explicitly. I did not read any sibling task directory, per the hard constraint.

## Step 3: Copy Shared Files — 2026-08-12T23:55:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1337_restaurant_surplus_food_rescue_logistics/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-13T00:10:00.000Z

All checks pass. The PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_1337_restaurant_surplus_food_rescue_logistics/workspace/PRD.md`.

**What was generated:** A 306-line prose PRD for the Restaurant Surplus Food Rescue Logistics domain. Structure: §1 Introduction (3 paragraphs from business context / system goals / technical commitments angles), §2 with 9 subsections (2.1 RBAC with per-role identity translation; 2.2 the fixed verbatim response-structure block, confirmed byte-identical to `section-2.2-response-structure.md`; 2.3 pagination; 2.4 logical clock and lazy state resolution; 2.5 common resource properties including the TemperatureLog no-`updated_at`/no-`version` exception; 2.6 OCC; 2.7 ownership masking; 2.8 the 12-tier validation priority order; 2.9 units/precision/rounding), §3 with 8 subsections organized by network-building → offer lifecycle → dispatch → driver run → safety verdict → failures/strikes → countersignature/ledgers → tax substantiation, §4 endpoint table (4 columns, all 33 endpoints), §5 error catalogue (2 columns, all 36 codes).

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 94 required, 94 present, 0 missing
- endpoints[].request_body: 59 required, 59 present, 0 missing
- endpoints[].query_params: 6 required, 6 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 12 checked, 12 expressed in prose (explicit numbered order in §2.8; receipt verified-set-first/rate-card-second sub-order in §3.8), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (expected_offer_version → ERR_STALE_OFFER_VERSION/412 on run creation; expected_donor_version → ERR_STALE_DONOR_VERSION/412 on receipt issuance; no race-framing language), 0 missing
- state_machines[].transitions: 51 checked, 51 fully expressed (from/to states, preconditions with error ids, side-effect cascades incl. donor/driver suspension teardowns and cooler quarantine path), 0 missing
- calculations[]: 11 checked, 11 fully expressed (danger-zone interpolation with inclusive 240-minute boundary, pinned half-up rounding order in enhanced tax rate with the 151/100/10 → 1260-cent worked example, reliability score 100/+5/−50/strict-below-60/reset-80, 3-strike inclusive suspension, capacity gates inclusive, ceil overage and liters), 0 missing
- validations[] conditions: 12 checked, 12 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 33 checked, 33 expressed, 0 missing
- entities[].fields[] structured content: 94 checked, 94 reconstructible (defaults, initial states, null-until-recorded semantics, computed aggregates), 0 missing
- sibling-branch symmetry: 7 groups checked (COLD_HELD/HOT_HELD predicates, standard/enhanced tax variants, donor/driver strike penalties, pickup/delivery fail stages, auto/pinned selectors, ACCEPT/DECLINE, UPHELD/WAIVED), 7 with equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 589
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Constraint compliance:** `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced. All 36 error IDs appear in §2/§3 prose (verified excluding the §5 table); no fuzzy/approximating words and no operator pseudocode (`==`, `>=`, `+=`, …) appear in §3.

## Resume Assessment — 2026-08-13T00:35:00.000Z

RESUME RUN. Prior run killed mid-flight. Directory audit:
- Step 2 (scaffold): COMPLETE — SCAFFOLD.yaml (86KB), SCAFFOLD_DIFFICULTY_DESIGN.yaml (105KB), SCAFFOLD_CORNER_DESIGN.yaml (170KB) all present, worklog entry confirms clean lint. Kept as-is.
- Step 3 (INSTRUCTION.md): COMPLETE. Kept.
- Step 4 (PRD): COMPLETE — workspace/PRD.md present, worklog reports all hard-contract checks PASS. Kept.
- Step 5 (unit tests): INCOMPLETE/TRUNCATED — test_helpers/ contains only types.py; test_suite/ is empty. REGENERATING.
- Step 6 (implementation): INCOMPLETE/TRUNCATED — routes/__init__.py imports routes.runs, routes.strikes, routes.rate_cards but those files do not exist (app would fail to boot); rescue-run/temperature/strike/receipt endpoints unimplemented (only 18 of 33 scaffold endpoint paths present). REGENERATING.
- Steps 7-9: not started.
Resuming at Step 5+6 (concurrent launch).

## Step 5: Generate Unit Tests (regenerated on resume) — 2026-08-13T01:15:00.000Z

Generation complete. All audits pass. Summary below.

## Files written

**`test_helpers/` (9 files)** — `/home/ubuntu/github/CodingPRD/tasks/task_1337_restaurant_surplus_food_rescue_logistics/test_helpers/`
- `types.py` (overwrote the stale file) — 12 entity TypedDicts + 14 enums; `TemperatureLog` correctly carries only `id`/`created_at` + reading fields (no `version`/`updated_at`)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per each of the 33 PRD §4 endpoints
- `api_errors.py` — all 36 error IDs with HTTP statuses, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` + receipt roll-up invariant checkers
- `factories.py`, `constants.py` (danger-zone/kill temps, 135-min reservation buffer, 45/240-min cleaning holds, reliability 100/+5/-50/60/80, strike limit 3, 1.25x overage)
- `test_users.py` — opaque `DispatchAdmin` constants (admin-1/2/3 for segregation-of-duties) + mandatory `make_*_headers(entity_id)` builders for the three entity-backed roles
- `fixtures.py` — tiered composites: primitive creators, `dispatch_run` (self-captures fresh OCC version), lifecycle walkers (`setup_confirmed_run`/`setup_picked_up_run`/`setup_delivered_run`/`setup_verified_run`), `issue_receipt` (self-captures donor version), plus scenario fixtures `setup_two_donors_with_identical_verified_rescues`, `setup_driver_suspension_cascade_scenario`, `setup_filed_strike_against_donor`
- `__init__.py` — barrel export

**`test_suite/` (conftest.py + 14 test files, 81 test functions)**

## Test counts per design queue
- **Queue A (Difficulty): 36 tests — all 18 instances covered with exactly 2 tests each.**
- **Queue B (Corner): 45 tests — all 39 non-stub instances covered (33 with 1 test, 6 with 2).**

## Instances skipped
None. All 18 difficulty instances and all 39 non-stub corner instances passed the PRD-first two-condition filter. The 10 `excluded_because:` stubs were not translated; all their `difficulty_instance` cross-references were verified to resolve to real §1.8 instance names.

## Self-audit results
- **Tag coverage (scripted):** 81/81 tests carry exactly one terminal `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line; every tag resolves to a real instance; zero tags point at stubs; no shortfalls (Difficulty ≥2, Corner ≥1).
- **Verbatim citation pass (scripted):** 118 quoted PRD citation spans extracted from docstrings; after fixing 14 initial mismatches (sentence-final `;` vs `.`, ellipsized priority-list quotes, one paraphrased envelope quote), **0 failures** — every citation survives a whitespace-normalized literal grep of PRD.md.
- **No skip/xfail/skipif anywhere** (grep-verified 0 hits).
- **Unique-derivability adjustments:** absolute entity-`version` pins (e.g. `== 1`, `== 6`, `== 3`) are not PRD-derivable (§2.5 never states the initial value), so all version assertions are relative to create-time captures (`v_created + 5`, `dv_stale + 1`, `ov + 1`) or freshness-based; `RateCard.card_version == 1/2` *is* asserted absolutely because PRD §3.8 explicitly says "starting at 1". Timestamp equality on `cleaning_ends_at`/`blocked_end` is asserted via prefix comparison (PRD pins content, not serialization precision).
- **Compile/import:** all 23 files compile; all test modules import cleanly against the pip-installed framework with signatures verified against the framework source. Nothing under `workspace/implementation/` was read or referenced.

## Step 6: Generate Implementation (regenerated on resume) — 2026-08-13T01:15:00.000Z

The implementation is complete. Summary:

## Files written/extended

All under `/home/ubuntu/github/CodingPRD/tasks/task_1337_restaurant_surplus_food_rescue_logistics/workspace/implementation/`:

**Created (the 3 missing route modules, 13 endpoints):**
- `routes/runs.py` — dispatch with full 12-tier validation ordering (schema → FK existence → cooler_ids-on-non-cold-chain → OFFER_NOT_OPEN → DRIVER_NOT_ACTIVE → OCC 412 → cert → window/cooler intervals → category → capacities → selector fallback in driver→agency→cooler order), list/get, respond (ACCEPT capacity re-check / DECLINE full release), record-pickup (kill screen, attestation, temp log), fail (both stage rulebooks, fault/reason consistency, SAFETY_DISPOSAL quarantine path, strike auto-filing with DRIVER/ADMIN reporter mapping), record-delivery (ARRIVAL log on attempt, verdict before overage per PRD §2.8, ceil 1.25x overage gate), verify-delivery (countersign, +5 reliability cap 100, window release), temperature-log and cooler-reservation listings.
- `routes/strikes.py` — per-run strike listing + adjudicate (FILED check, segregation-of-duties 403, UPHELD penalties: donor strike_count→suspend at 3 with cascade; driver −50 floor 0→suspend strictly below 60 with cascade).
- `routes/rate_cards.py` — create with half-open non-overlap, monotonic `card_version` from 1, rejected creations don't consume versions.

**Extended:** `services.py` — exact Decimal span math for the danger-zone interpolation verdict, plus equipment lifecycle helpers (book_window, create_reservation with the 135-min buffered interval, checkout/return/quarantine transitions) and temperature-log helpers (no `updated_at`/`version` per PRD §2.5).

**Kept from the partial run (verified correct):** `app.py`, `db.py` (empty store, no seeding), `errors.py`, `middleware.py`, `response.py` (scaffold envelope: `meta`/`response_type`/`data`, pagination `limit`/`offset`/`total_count`/`has_more` with defaults 10/0/max 100), `util.py`, `routes/{__init__,clock,donors,agencies,drivers,coolers,offers}.py`, `start.sh` (guarded pip install, `exec`, `0.0.0.0:$PORT`), `requirements.txt`.

## Endpoint coverage: 33/33
All 33 scaffold endpoints are registered and exercised (34th Flask route is the framework's static handler).

## Verification
- `python3 -c "import app"` → BOOT OK; also booted via `bash start.sh` with a custom `PORT` and served live requests.
- 244 dev-only smoke assertions passed across five suites covering: auth/RBAC and ownership masking (404-masking per role), all lifecycle state machines, lazy offer expiry (OPEN/MATCHED→EXPIRED with run teardown, strict `>` boundary), lazy cooler CLEANING/QUARANTINED resolution (+45/+240 min), both OCC guards (412), driver/agency selector ranking and best-fit, cooler buffered-interval semantics, kill screens (COLD ≥70, HOT ≤100), danger-verdict interpolation with the inclusive 240-minute boundary, the 3-failure offer expiry, donor 3-strike suspension cascade, driver suspension cascade (PROPOSED→DECLINED, CONFIRMED→FAILED_PICKUP + SYSTEM strike), donor-cancel SYSTEM strike vs admin-cancel no-strike, receipt issuance with pinned half-up rounding (fmv=151/basis=100 → 126/lb), amendment/supersede, enhanced vs standard deductible, and pagination meta.

One judgment call worth noting: cooler candidate eligibility requires lazily-`AVAILABLE` status (a `RESERVED` cooler answers `ERR_COOLER_UNAVAILABLE` even for a disjoint interval), per PRD §3.1's single-cycle cooler status model and the state machine's AVAILABLE→RESERVED precondition; the buffered-adjacency rule governs released/inactive reservations.

## Step 7: Run Tests and Iterate — 2026-08-13T01:40:00.000Z

All 8 rounds pass — 84/84 each.

## Summary

- **Iterations run**: 3 parallel 8-round sweeps.

- **Tests deleted**: None. All 17 initially failing tests traced to either PRD-faithful implementation bugs or test_helpers/test_suite bugs that could be corrected to align with PRD.

- **Fixes applied to `test_helpers/`**:
  - `/home/ubuntu/github/CodingPRD/tasks/task_1337_restaurant_surplus_food_rescue_logistics/test_helpers/fixtures.py` — `issue_receipt`: added a `set_clock(period_end)` call before issuing, since PRD §3.8 requires `period_end` to not lie after the current logical clock. Fixed 6 tests in test_11 and test_14 that were hitting `ERR_INVALID_REQUEST` instead of the receipt-specific gates they were designed to exercise.
  - Same file — `setup_confirmed_run`: sized the default cooler's `capacity_liters` to fit the scenario's `estimated_weight_lbs` (PRD §3.3 requires `ceil(weight * 0.5)` liters). Fixed `TestEstimatedVsVerifiedWeight` tests that were tripping `ERR_INSUFFICIENT_COOLER_CAPACITY` because the default 30L cooler couldn't hold an 80-lb estimate.
  - Same file — `setup_two_donors_with_identical_verified_rescues._rescue`: moved `set_clock("2026-08-02T09:30:00Z")` to before `create_offer(publish=True)` so `pickup_window_end` lies after the current clock (PRD §3.2 ERR_PICKUP_WINDOW_PAST precondition). Fixed both `TestStandardVsEnhancedDivergence` tests.

- **Fixes applied to `test_suite/`**:
  - `/home/ubuntu/github/CodingPRD/tasks/task_1337_restaurant_surplus_food_rescue_logistics/test_suite/test_05_dispatch_selectors.py::TestAgencyCapacityInclusiveBoundary.test_one_pound_over_full_capacity_rejected` — pinned a fresh cooler `C3` instead of reusing the already-RESERVED `C1`. Per PRD §2.5's fixed error order, `ERR_COOLER_UNAVAILABLE` (priority 9) fires before `ERR_AGENCY_CAPACITY_EXCEEDED` (priority 11), so reusing C1 was tripping the wrong gate.
  - `/home/ubuntu/github/CodingPRD/tasks/task_1337_restaurant_surplus_food_rescue_logistics/test_suite/test_07_run_lifecycle.py::TestDeclineRematchCycle.test_reverted_offer_dispatches_again_rebooking_same_resources` — corrected the version assertion from `v_created + 5` to `v_created + 4`. `v_created` was captured AFTER `create_offer(publish=True)`, so create+publish were already folded in; only the four subsequent mutations (dispatch, decline, dispatch, accept) increment the version.

- **Fixes applied to `implementation/`**:
  - `/home/ubuntu/github/CodingPRD/tasks/task_1337_restaurant_surplus_food_rescue_logistics/workspace/implementation/services.py::cooler_is_candidate` — relaxed the status check from `cooler["status"] != "AVAILABLE"` to excluding only `CLEANING`/`QUARANTINED`/`CHECKED_OUT`. A RESERVED cooler whose existing reservation's interval does NOT overlap the new request remains a candidate, matching the PRD §3.3 reading "candidate coolers are those lazily AVAILABLE with no reservation in RESERVED or CHECKED_OUT whose buffered blocked interval overlaps the new one" — the interval test does the real work; a RESERVED status alone should not preclude non-overlapping reuse (this is what makes the buffered-edge test expressible). Fixed `TestCoolerReservationBufferedInterval.test_pickup_at_buffered_edge_allowed` plus the `setup_driver_suspension_cascade_scenario` callers in test_09 that intentionally reuse `c1` for non-overlapping windows.

- **Final state**: All 8 parallel rounds passed 84/84.

## Step 8: Finalize PRD — 2026-08-13T01:50:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1337_restaurant_surplus_food_rescue_logistics/workspace/PRD_FINALIZED.md` is written.

## Line counts
- `PRD.md`: 305 lines; `PRD_FINALIZED.md`: 305 lines — 0% line-count delta (both edits were inline paragraph revisions; 2 of 305 lines' text, ~0.66%, changed).

## Changes (one Step 7 item was a genuine PRD-silence/mismatch; the rest were fixture/test bugs already pinned by the PRD)

- **§3.3 (cooler candidacy, line 162)** — revise — Replaced "Candidate coolers are those lazily `AVAILABLE` with no reservation in `RESERVED` or `CHECKED_OUT` whose buffered blocked interval overlaps the new one" with an exact description of the implemented rule: after lazy resolution, a cooler is a candidate unless its status is `CLEANING`, `QUARANTINED`, or `CHECKED_OUT`, and unless one of its own `RESERVED`/`CHECKED_OUT` reservations' buffered blocked intervals overlaps the new one — so a cooler still `RESERVED` from an earlier dispatch remains a candidate for a non-overlapping new interval. The pinned-mode clause was revised in lockstep (a cooler failing that same test answers `ERR_COOLER_UNAVAILABLE`). — `implementation/services.py:617-639` (`cooler_is_candidate`), call sites `implementation/routes/runs.py:162-168` (pinned) and `implementation/services.py:642-661` (auto).
- **§3.3 (dispatch effects, line 164)** — revise — "Each selected cooler moves from `AVAILABLE` to `RESERVED`…" → "Each selected cooler stands at `RESERVED`… a cooler that was `AVAILABLE` moves to `RESERVED`, and one already `RESERVED` from a non-overlapping earlier dispatch simply remains `RESERVED`." — `implementation/services.py:740-754` (`create_reservation` sets `cooler["status"] = "RESERVED"` unconditionally).

No other edits: the remaining Step 7 items trace to fixture/test bugs where the PRD already determines behavior (§3.8 `period_end` clock gate, §3.3 `ceil(weight*0.5)` liters, §3.2 `ERR_PICKUP_WINDOW_PAST` at publish, §2.8 fixed error order `ERR_COOLER_UNAVAILABLE` tier 9 before `ERR_AGENCY_CAPACITY_EXCEEDED` tier 11, §2.5 version-increment-on-every-mutation) — prose kept verbatim.

## Per-edit pre-edit search log

**Edit 1 (§3.3 candidacy)**
- (a) Subject: cooler eligibility at dispatch, both auto and pinned selector modes.
- (b) Enumerated impl paths: `implementation/services.py:617-639` (`cooler_is_candidate` — single definition; status exclusion is exactly `CLEANING`/`QUARANTINED`/`CHECKED_OUT`, interval test restricted to that cooler's own `RESERVED`/`CHECKED_OUT` reservations via `res["cooler_id"] != cooler["id"]` filter); `implementation/routes/runs.py:162-168` (pinned-mode loop → `ERR_COOLER_UNAVAILABLE`); `implementation/services.py:642-661` (`select_coolers` auto waterfall); `implementation/services.py:85-116` plus `services.py:61` (`resolve_lazy` runs in `before_request`, so past-deadline `CLEANING`/`QUARANTINED` coolers are already `AVAILABLE` when candidacy is evaluated — this is what "lazily" must mean); lifecycle writers `services.py:369-376` (release cascade → `AVAILABLE`), `740-754`, `760-797` (pickup/return/quarantine); `implementation/routes/coolers.py:26` (creation enters `AVAILABLE`). Also cross-checked PRD §2.8 tier 9 and §3.1 cooler-cycle prose for consistency.
- (c) Wording adjustment: an earlier draft phrased candidacy as "lazily `AVAILABLE` or `RESERVED`-but-non-overlapping"; that was rejected because it mis-states the mechanism (an `AVAILABLE`-status cooler with an overlapping reservation is also excluded, and the interval test — not the status — is the operative gate). Final wording mirrors the code: status-exclusion set plus interval test, with the `RESERVED`-reuse consequence stated explicitly. Scope limited to candidacy; §3.1's cycle narrative left untouched.

**Edit 2 (§3.3 dispatch effects)**
- (a) Subject: cooler status transition applied to selected coolers at dispatch commit.
- (b) Enumerated impl paths: `services.py:740-754` (`create_reservation` — unconditional `cooler["status"] = "RESERVED"`); candidate sources feeding it (`runs.py:217` pinned set, `runs.py:227` auto set), both filtered by `cooler_is_candidate`, so a selected cooler's status is `AVAILABLE` or `RESERVED` only; verified no other writer of cooler `RESERVED` status exists (`grep` over `services.py`/`routes/`).
- (c) Wording adjustment: replaced the universal "moves from `AVAILABLE` to `RESERVED`" with "stands at `RESERVED`" plus the two sub-cases, since the reuse path introduced by Edit 1 performs no transition.

## Step 9: Complete PRD — 2026-08-13T02:00:00.000Z

All edits are in-place revisions of existing paragraphs — 30 paragraph-lines rewritten, no lines added or removed, no new sections.

## Summary

**Source vs output:** `PRD_FINALIZED.md` (305 lines, 55,354 chars) → `PRD_COMPLETED.md` (305 lines, 60,379 chars); char-delta **+5,025**.

**Counts:** 22 ambiguity-pins, 5 mismatch-revisions (27 total changes across 21 paragraphs).

### Mismatch-revisions (PRD described behavior impl does not exhibit)
- **§2.8** — revise — mismatch — the strict global check-order claim now acknowledges two endpoint-level interleavings (dispatch checks pinned-driver state before the version guard; record-delivery checks `arrival_time` vs `pickup_time` after run-state), matching actual check sequences — `implementation/routes/runs.py:127-140`, `runs.py:508-517`
- **§3.3** — revise — mismatch — replaced "a stale version answers `ERR_STALE_OFFER_VERSION` before anything else is attempted" with the impl's actual order: existence → `ERR_OFFER_NOT_OPEN` → pinned-driver state → stale version — `implementation/routes/runs.py:98-140`
- **§3.3** — revise — mismatch — pinned-driver capacity error (`ERR_DRIVER_CAPACITY_EXCEEDED`) fires after the pinned-agency acceptability check, not before it as the §2.8 tier order implies; pinned explicitly — `implementation/routes/runs.py:171-182`
- **§3.3** — revise — mismatch — "the agency's committed counter rises by the snapshot / `pending_estimated_lbs` rises" wording replaced with "covers" language, since impl computes all aggregates dynamically and never stores/increments them — `implementation/services.py:188-255`
- **§3.6** — revise — mismatch — removed "UPHELD stamps `adjudicated_by_user_id`/`adjudicated_at`" (implying WAIVED does not); impl stamps both outcomes and both are terminal — `implementation/routes/strikes.py:53-56`

### Ambiguity-pins (PRD silent; pinned to impl)
- **§2.2** — `api_request_id` = `req_` + 20 random alphanumerics; `api_request_timestamp` is wall-clock, not the logical clock — `implementation/response.py:8-21`
- **§2.3** — non-integer/out-of-range/negative `limit`/`offset` → `ERR_INVALID_REQUEST`; `has_more` ⇔ `offset+limit < total_count`; `created_at` ties break by creation order — `implementation/util.py:119-156`
- **§2.4** — clock-set accepts any well-formed ISO 8601 (backwards allowed), response carries `current_utc` verbatim — `implementation/routes/clock.py:12-19`
- **§2.4** — offer lazy expiry is strict (`now > pickup_window_end`; end exactly at the clock survives) — `implementation/services.py:90`
- **§2.5** — `version` starts at 1; all impact/capacity aggregates are computed-on-read, never stored — `implementation/services.py:68-78,274-294`
- **§2.8** — tier-3 includes non-JSON / non-object bodies — `implementation/util.py:33-45`
- **§2.9** — submitted temperatures rounded half-up to 1 decimal at storage; stored value drives screening/verdicts — `implementation/services.py:462-465,806-818`
- **§3.1** — `ein` validated only as a non-empty string — `implementation/routes/donors.py:47`
- **§3.1** — agency capacity ceilings are non-negative (zero allowed) — `implementation/routes/agencies.py:38`
- **§3.1** — `vehicle_capacity_lbs` non-negative (zero accepted) — `implementation/routes/drivers.py:45-47`
- **§3.1** — `capacity_liters` must be an integer > 0; delivery-stage failure is the ordinary-return/quarantine path to `RETURNED`/`QUARANTINED_HOLD`, not `RELEASED` — `implementation/routes/coolers.py:19-21`, `services.py:772-799`
- **§3.2** — client-supplied `requires_cold_chain` is accepted (whitelisted) and silently ignored; offer creation has no donor-`ACTIVE` gate — `implementation/routes/offers.py:57-114`
- **§3.2** — donor-cancel auto-strike carries `reason` `OTHER` — `implementation/routes/offers.py:47-49`
- **§3.2** — `current_run_id` is written at dispatch and never cleared — `implementation/routes/runs.py:252-254`
- **§3.3** — duplicate `cooler_ids` de-duplicated; `cooler_ids: null` treated as omitted; pinned empty list on cold-chain falls back to auto-selection — `implementation/routes/runs.py:88-117,209-227`
- **§3.3** — auto cooler mode also covers omitted/null/empty; non-cold-chain dispatch never consults `cooler_slot_count` — `implementation/routes/runs.py:206-227`
- **§3.4** — non-cold-chain pickup/delivery may omit the temp reading (no log written); cold-chain pickup with missing `pickup_temp_f` is refused with `ERR_SAFETY_VIOLATION_AT_PICKUP`; verdict gate runs before the overage gate — `implementation/routes/runs.py:346-373,504-549`
- **§3.5** — verdict uses the most recent `ARRIVAL` log; every delivery attempt appends a log; missing arrival reading or missing pickup log on cold-chain → violation — `implementation/services.py:828-837`, `runs.py:519-541`
- **§3.6** — pickup-stage `AGENCY_CLOSED`/`OVER_CAPACITY`/`OTHER` admit any `fault_party`; fault strike subject is the run's donor site / assigned driver — `implementation/routes/runs.py:419-424,478-483`
- **§3.6** — `SAFETY_DISPOSAL` documentation/fault checks are tier-3 (pre-state); on `CONFIRMED` it answers `ERR_RUN_NOT_IN_EXPECTED_STATE`; delivery-stage `DONOR_NO_SHOW`/`DRIVER_NO_SHOW`/`SAFETY_REJECTED`/`OTHER` admit any fault party — `implementation/routes/runs.py:394-458`
- **§3.6** — upheld strike against an already-`SUSPENDED` subject applies counters without a second cascade; `DEACTIVATED` donors unreachable — `implementation/routes/strikes.py:57-81`
- **§3.6** — donor-suspension cascade files no strikes — `implementation/services.py:421-437`
- **§3.8** — rate-card rates are integers with no further constraint (basis may exceed FMV) — `implementation/routes/rate_cards.py:32`
- **§3.8** — receipt issuance has no donor-`ACTIVE` requirement, only the version guard — `implementation/routes/donors.py:147-170`
- **§3.8** — receipt `lines` emitted in fixed category order `COLD_HELD`, `HOT_HELD`, `PRODUCE`, `SHELF_STABLE` — `implementation/services.py:696-726`
