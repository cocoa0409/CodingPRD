# Worklog — task_1634_broiler_contract_grow_out_settlement

## Step 1: Create task directory — 2026-08-14T03:41:00.000Z

Task directory `tasks/task_1634_broiler_contract_grow_out_settlement/` and `workspace/` pre-created and pre-assigned by the pipeline launcher; Step 1 treated as DONE per invocation args. No index scan performed; no other task directory touched.

## Step 2: Generate scaffold — 2026-08-14T04:12:20.000Z

Clean lint confirmed. All three files are written and validated.

**VERDICT block (verbatim):**
```
Coverage
  §1.5 endpoints declared:    55
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     30
  Calls scanned (§1.8+§1.9):  637

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Summary of generated scaffold — task_1634_broiler_contract_grow_out_settlement

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1634_broiler_contract_grow_out_settlement/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`

**Complexity profile**: primary archetype `pricing_engine` (tournament/ranking settlement), secondary `posture_driven_gating` (house downtime/quarantine posture gates placement); layers: dual-variant calculation, cascading side effects, rate/threshold triggers, derived-field reconciliation, optimistic concurrency. Hybrid topology, branching state shape, segregation-of-duties role model, immediate consistency.

**Entities (14)**: Grower, GrowerContract, House, Flock, ChickPlacement, FeedDelivery, MortalityReport, CatchSchedule, CatchCrew, WeightTicket, BiosecurityAudit, SettlementGroup, Settlement, GrowerLoan.

**State machines (4)**: GrowerContract (DRAFT→ACTIVE→RENEWAL_PENDING→RENEWED with reject loop, terminal EXPIRED/TERMINATED), House (ACTIVE/PLACED/DOWNTIME/QUARANTINED fork-join with FAIL-audit quarantine branch), Flock (PLANNED→PLACED→GROWING→CATCH_SCHEDULED→HARVESTED→SETTLED plus CONDEMNED_LOSS branch), Settlement (PENDING↔DISPUTED revision cycle, APPROVED→PAID terminal).

**Calculations (5)**: adjusted_fcr (raw vs waste-credit variants), performance_score (weighted scoring, provisional vs final variants, pinned evaluation order over group averages), settlement_amounts (tiered rank uplift + conditional FCR bonus + condemnation deduction + loan waterfall, per-line round_half_up then sum), loan_outstanding_recompute (oldest-first waterfall), grower_performance_rating (rolling 3-flock window).

**Validations (16 priorities)**, **endpoints (55)** including `POST /api/_clock/set_current_utc` with fixed startup default 2026-08-01T00:00:00Z, **17 error codes**, **5 roles** (IntegratorAdmin opaque, Grower entity-backed, ServiceTech/LivehaulScheduler/SettlementAnalyst opaque) with segregation-of-duties flavor (grower reports mortality; integrator confirms placements; analyst approves settlements; scheduler completes catches).

**Difficulty design (§1.8): 18 instances, 2 per rule**, with differentiators honored: dual-variant calc on settlement money vs FCR domains; combinatorial modes (a) tiered multi-branch formula and (b) pinned rounding order (deduction 515 from 51/9700 condemnation); non-linear machines on Settlement (dispute cycle) vs House (quarantine fork-join); cascades of depth 3 (catch-complete → flock → house → group averages) and depth 2 (approve → loan waterfall → grower mirror); priority conflicts on state-vs-safety and temporal-vs-constraint pairs; boundaries on condemnation >0.30 (exactly 0.30 rejected, 0.301 accepted) and crew capacity at exactly max; cross-entity gates Settlement→SettlementGroup and GrowerContract→GrowerLoan; temporal overlap with house half-open date semantics vs crew per-day aggregate capacity; compensating invariants on loan outstanding conservation (120000 − 46875 = 73125) and crew-capacity restoration on cancel.

**Corner design (§1.9): 30 instances** across entities, state machines, calculations, validations, endpoints, errors, RBAC (incl. entity-backed ownership denial), cross-cutting layers (both OCC rules with `${var}`-driven versions), and consistency model — with 5 `excluded_because` stubs citing §1.8 coverage.

All pinned numeric asserts were precomputed with Python (provisional 265625 vs final 299625, waterfall 46875/73125, dispute-loop 31250, OCC recompute 37500, deduction 515, rounding net 265187). Two OCC-literal and one reverse-reachability lint violations were found and fixed; final run is clean.

## Step 3: Copy shared files — 2026-08-14T04:13:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1634_broiler_contract_grow_out_settlement/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T04:20:00.000Z

All contracts pass. The PRD is complete.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1634_broiler_contract_grow_out_settlement/workspace/PRD.md` — 308 lines.

**Section list:**
- §1. Introduction (3 paragraphs — tournament-business framing, system scope, role segregation)
- §2. Global Specifications (9 subsections): 2.1 Roles & headers, 2.2 API Response Structure (verbatim block), 2.3 Pagination, 2.4 Common Resource Properties, 2.5 Nested Resource Retrieval, 2.6 Monetary Values/Ratios/Rounding, 2.7 Optimistic Concurrency Control, 2.8 Validation Ordering (all 17 rules in fixed priority), 2.9 The Logical Clock
- §3. Business Logic (10 subsections): onboarding, contract lifecycle, flock placement & grow-out, biosecurity/downtime/release, catch scheduling & harvest, condemned-loss, tournament groups & locking, settlement amounts (rank/tier/bonus/deduction/repayment), loans & waterfall, approval/dispute/payment
- §4. Endpoint Definitions — 55 rows, 4 columns each
- §5. Error Code Catalogue — 17 rows, 2 columns

**Contract verification (all PASS):**
- **Contract 1 Field-Name Coverage:** entities 67/67, request_body 41/41, query_params 8/8 — every field name appears in backticks (including `status`, `house_status`, `expected_flock_version`, `expected_grower_version`, `to_iso8601`)
- **Contract 2 Rule Coverage:** all 25 state-transition pairs expressed as explicit `FROM` → `TO` pairs; both OCC rules named with endpoint + occ field + error id + HTTP 412; all 5 calculations fully expressed in prose with every constant embedded (2,000 lb waste credit, 35-day min age, 0.30 condemnation threshold, 0.005 allowance, 40¢ rate, 14-day downtime, 21-day condemnation downtime, 3-flock rating window, recovery 1–50, ≥7 quarantine days, 98% FCR bonus tier, 1.5/0.8/0.2 cent rank tiers at 0.75/0.50/0.25 percentiles, 50/20/100 score weights, per-line-then-sum rounding); all 17 validations listed in §2.8 priority order with error ids; applies-to scopes enumerated (e.g. `ERR_HOUSE_IN_DOWNTIME` guarding both placement scheduling and confirmation); sibling branches symmetric (renew vs reject, dispute/resolve/pay, catch complete vs cancel); terminal states `RENEWED`/`EXPIRED`/`TERMINATED` all named
- **Contract 3 §3 Path Purity:** 368 backticked tokens scanned in §3 — zero path tokens, zero bare HTTP methods, zero method+path combos

Note: the initially reported "67 missing fields" was an artifact of my verification script counting fence backticks and shifting pairing; the PRD itself was correct, and after fence-stripping the only genuine gaps were `status`, `house_status`, and the `EXPIRED` state name, all three repaired via targeted edits.

## Step 5: Generate unit tests — 2026-08-14T04:55:00.000Z

Complete. Test infrastructure and suite generated for `task_1634_broiler_contract_grow_out_settlement`, with all audits passing.

## Test counts

**67 tests total** (pytest collection verified clean against `prd_bench_local_runner`).

- **Queue A (Difficulty, §1.8): 17 of 18 instances translated, 34 tests** (exactly 2 per translated instance). Every translated instance carries `Design: Difficulty/<rule_id>/<instance.name>`.
- **Queue B (Corner, §1.9): all 25 non-stub instances translated, 33 tests** (≥1 each; larger instances split into 2). The 5 `excluded_because:` stubs (`error_group_not_locked`, `error_house_in_downtime`, `error_crew_overbooked`, `error_condemnation_threshold`, `error_renewal_blocked` — all `_covered_by_difficulty`) were **not** translated; their `difficulty_instance` cross-references were verified to resolve to real §1.8 instances.

## Skipped instance (1, with reason)

- **`Difficulty/combinatorial_formula/per_line_rounding_then_sum_mode_b`** — fails the PRD-first two-condition filter (unique derivability). The instance pins `condemnation_deduction_cents == 515`, computed from full-precision `51/9700 − 0.005`. But PRD §2.6 states `condemnation_pct` is "computed and stored to exactly 4 decimal places using round-half-up" (→ 0.0053), and PRD §3.8 defines the deduction from "the flock's `condemnation_pct`" — the stored quantity — which yields 600. Two PRD-only implementers plausibly ship 515 vs 600; the gap stays a gap (no placeholder, no weakened assertion).

## Adjudications applied (not skips)

- `Corner/entities/grower_creation_success_and_defaults`: the instance's `version == 1` assertion is not PRD-pinned (PRD §2.4 never states the initial version), so the test asserts only the PRD-pinned defaults (status ACTIVE, performance_rating null, loan_outstanding_cents/house_count 0, bare-UUID id).
- `Corner/cross_cutting_complexity_layers/derived_fields_reconcile_on_mortality_post`: the yaml's literal `condemnation_pct == 0.00412371` contradicts PRD §2.6's 4-decimal storage rule; the test asserts the PRD-derivable `0.0041` (and exact `livability_pct == 0.97`).
- Several §1.8/§1.9 recipes read a settlement after group lock without any `recompute-settlement` call; PRD §3.7 only creates settlement rows via that operation. Fixtures therefore insert a PROVISIONAL preview (recompute) before lock — outcome-preserving under every faithful PRD reading; all asserted amounts unchanged.

## Files written

`test_helpers/` (all under `/home/ubuntu/github/CodingPRD/tasks/task_1634_broiler_contract_grow_out_settlement/`): `__init__.py` (barrel), `types.py` (13 status/type enums + 14 TypedDicts, all with full common fields per PRD §2.4), `api_client.py` (44 endpoint methods), `api_errors.py` (17 errors + framework HTTP-status registration), `assertions.py` (14 entity assertions, settlement line-balance invariant), `factories.py`, `constants.py` (waste credit 2000, min grow 35d, downtime 14d, condemned-loss 21d/0.30, allowance 0.005, rate 40c, rating window 3, recovery 1–50), `test_users.py` (5 roles + `make_grower_headers` for the entity-backed Grower role + `ANONYMOUS_HEADERS`), `fixtures.py` (single-step helpers incl. OCC loan handshake and preview/lock, plus composites: `setup_growing_flock`, `setup_harvested_flock`, `setup_locked_settlement`, `setup_paid_settlement`, `setup_two_grower_tournament`, `setup_two_loan_grower`).

`test_suite/`: `conftest.py` + `test_01_growers_contracts.py` (9), `test_02_placements_growout.py` (11), `test_03_catch_and_harvest.py` (13), `test_04_biosecurity_downtime.py` (2), `test_05_settlement_calculation.py` (10), `test_06_settlement_lifecycle.py` (8), `test_07_loans_and_repayment.py` (7), `test_08_condemned_loss.py` (2), `test_09_rbac.py` (4).

## Verification

- `py_compile` clean; pytest collects 67 tests with zero import errors.
- Design-tag audit (AST + getdoc): every test has exactly one Design line as its final docstring line; all tags resolve to real instances; coverage 17/18 queue A (the 18th is the adjudicated skip) and 25/25 queue B non-stub.
- Citation audit: all 102 quoted docstring fragments survive normalized literal grep of `workspace/PRD.md`; no `skip`/`skipif`/`xfail` markers anywhere.

## Step 6: Generate implementation — 2026-08-14T04:55:00.000Z

Implementation complete and verified. Summary:

## File list
All under `/home/ubuntu/github/CodingPRD/tasks/task_1634_broiler_contract_grow_out_settlement/workspace/implementation/`:
- `start.sh` (executable, guarded `pip install`, `exec python3 app.py`, `$PORT` default 10000, `0.0.0.0`)
- `requirements.txt` (flask)
- `app.py` — entry point, global request lock, error handlers (ApiError / 404 / 405 / 500 all envelope-shaped)
- `db.py` — in-memory stores (all empty at boot, zero seeding) + logical clock (default exactly `2026-08-01T00:00:00Z`) + insertion sequence
- `errors.py`, `response.py`, `middleware.py`, `helpers.py`, `utils.py` — envelope (`meta.api_request_id`/`api_request_timestamp` with 3 fractional digits, `response_type`, `data`; error body `data.error_id`/`message`), `X-User-ID`/`X-User-Role` auth, RBAC + Grower ownership, pagination (`limit`/`offset`/`total_count`/`has_more`, default 10, clamped 1..100)
- `services/domain.py` — all calculations (adjusted_fcr, performance_score, settlement_amounts with rank tiers/FCR bonus/condemnation deduction/loan repayment, loan waterfall, group averages, performance rating) and cascades (placement confirm, harvest, condemned loss, audit FAIL, approve, lock)
- `routes/` — `growers.py`, `contracts.py`, `houses.py`, `flocks.py`, `placements.py`, `schedules.py`, `groups.py`, `settlements.py`, `crews.py`, `clock.py`

## Endpoint count
All **55** endpoints from PRD §4 are implemented (8 growers, 8 contracts, 7 houses, 16 flock-scoped, 2 placements, 2 catch-schedules, 4 settlement-groups, 4 settlements, 3 catch-crews, 1 clock).

## Verification
- Fresh-boot via `start.sh` confirmed: empty store, clock default correct, responds within ~2s.
- A 114-assertion spec suite (full grow-out arc, tournament math hand-verified: adj_fcr 1.8/1.86, group avg 0.00255→0.0026 half-up, scores 100.5697/99.4403, tier uplift 0.8, bonus/deduction/repayment lines, lock→approve→pay, waterfall 25000 against 100000 loan, renewal/upgrade gate, downtime/quarantine, condemned loss) — all pass.
- A 43-assertion edge suite (4-way rank tiers 1.5/0.8/0.2/0, score tie-break by live_weight, multi-loan waterfall oldest-first with REPAID transitions, OCC 412s and priority ordering 6-before-16 and 9-before-10, after-midnight date rule, cancel paths, pagination clamps) — all pass. No 500s in server logs.
- Test servers I started were killed afterward; the concurrent test-generation process's server was left untouched.

## Key ambiguity interpretations
- **Multiple ISSUED loans**: the formula's singular `loan.recovery_pct` → oldest ISSUED loan's rate (consistent with the oldest-first waterfall).
- **OCC field omitted**: check skipped (per skill guidance); any provided mismatched value → 412.
- **Preconditions with no cataloged error id** (contract activation grower/house-count gates, release-downtime/quarantine guards, renewal-request after term_end, catch completion without weight tickets, double-suspend) → `ERR_INVALID_STATE` 409.
- **Malformed/missing payload fields** (catalog has no generic 400): nearest cataloged 422 (`ERR_QUANTITY_INVALID`, or `ERR_LOAN_TERMS_INVALID` for loan terms); out-of-range `limit`/`offset` are clamped, never rejected.
- **Feed/mortality/weight creation carry no flock-state gate** (scaffold lists none); side effects are conditional (feed flips PLACED→GROWING only from PLACED; livability stays null until placement).
- **House cascade tolerances**: confirm moves a DOWNTIME house with an expired window to PLACED (PRD §3.3's guard text admits this path); FAIL audit on a PLACED house is recorded without status change (state machine defines the cascade only from ACTIVE/DOWNTIME); FAIL on QUARANTINED extends `downtime_until` via max.
- **`performance_score` stays null until SETTLED** (entity table wins); provisional ranking uses transient, unpersisted scores for HARVESTED members.
- **Rating tie-break "later settled date"**: no such field exists — proxied by flock `updated_at` DESC, then creation order ASC.
- **Timestamps derive from the logical clock** (matches sibling-task convention and the deterministic-clock design); insertion sequence breaks `created_at` ties for stable list order and oldest-first waterfalls.
- **Clock echo** normalized to `YYYY-MM-DDTHH:MM:SSZ` (matching the PRD's default literal); fractional digits only when set with sub-second precision.
- **After-midnight rule**: `now > midnight(date)` — release-downtime at exactly midnight of `downtime_until` still blocked; renewal request at exactly midnight of `term_end_date` allowed.
- **Group `SETTLED` and loan `CLOSED`**: no trigger/endpoint specified anywhere — left unreachable rather than invented.

## Step 7: Run tests and iterate — 2026-08-14T05:00:00.000Z

**Summary — task_1634_broiler_contract_grow_out_settlement**

- **Iterations run**: 1 (single 8-round parallel sweep; no fixes needed).
- **Result**: All 8 rounds passed 67/67 tests — 0 failed, 0 errors, 0 skipped per round (~96s wall time per round under `--isolation per-test-server`). Per-test statuses verified in every `results.{1..8}.json`: 67 × `passed` in each round.
- **Tests deleted**: none.
- **Fixes applied to `test_helpers/`**: none.
- **Fixes applied to `test_suite/`**: none.
- **Fixes applied to `implementation/`**: none.

The existing implementation, test suite, and test helpers were already mutually consistent and PRD-faithful: the 8-round stability sweep surfaced no failures and no flakiness, so no diagnostic steps (STEP 0–3) were triggered.

## Step 8: Finalize PRD — 2026-08-14T05:00:30.000Z

SKIPPED per the skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the implementation exhibits; no `PRD_FINALIZED.md` produced. Step 9 will start from `PRD.md`.

## Step 9: Complete PRD — 2026-08-14T05:15:00.000Z

Done. All 31 edits are applied to `/home/ubuntu/github/CodingPRD/tasks/task_1634_broiler_contract_grow_out_settlement/workspace/PRD_COMPLETED.md` (copied from PRD.md, then edited in place; PRD.md untouched).

**Size:** PRD.md = 308 lines / 41,532 chars → PRD_COMPLETED.md = 310 lines / 46,684 chars (char-delta +5,122, line-delta +2; diff touches 30 existing lines plus 2 added lines).

**Counts:** 25 ambiguity-pins, 6 mismatch-revisions (31 changes total).

**Changes:**

- §2.1 — insert — ambiguity — grower-scoped routes (`/api/growers/{id}` + sublists) check ownership before existence (403 for any foreign id even if nonexistent); all other resources resolve path first (404) then ownership — `implementation/routes/growers.py:21-25`, `implementation/middleware.py:51-59`, `implementation/routes/houses.py:69-72`
- §2.2 — insert — ambiguity — undefined path → `ERR_NOT_FOUND` (404); unsupported method → `ERR_NOT_FOUND` with HTTP 405; unexpected failure → `ERR_INTERNAL` (500) — `implementation/app.py:56-66`
- §2.3 — insert — ambiguity — out-of-range/unparseable `limit`/`offset` are clamped/defaulted, never rejected — `implementation/middleware.py:70-91`
- §2.3 — insert — ambiguity — created_at ties broken by insertion order; exact-match query filters enumerated (`status`, `house_status`, `settlement_group_id`/`contract_id`/`status`, `catch_date`); `total_count` counts the filtered set — `implementation/utils.py:156-158`, `implementation/routes/growers.py:56-63,133-140`, `implementation/routes/flocks.py:99-109`, `implementation/routes/houses.py:174-180`, `implementation/routes/crews.py:42-47`
- §2.7 — revise — mismatch — `expected_flock_version` is optional; check skipped when omitted or null (was "requires") — `implementation/routes/flocks.py:370-378`
- §2.7 — revise — mismatch — `expected_grower_version` likewise optional/skipped — `implementation/routes/growers.py:86-94`
- §2.8 — insert — ambiguity — field-level validation failures (missing/empty/non-integer/malformed/out-of-enum) map to the endpoint family's 422: `ERR_QUANTITY_INVALID` generally, `ERR_LOAN_TERMS_INVALID` on loan issuance — `implementation/helpers.py:19-60`, `implementation/routes/growers.py:96-100`, `implementation/routes/flocks.py:22-35`
- §2.9 — insert — ambiguity — all server timestamps (`api_request_timestamp`, `created_at`, `updated_at`) render from the logical clock; clock endpoint accepts any ISO 8601 instant (date-only = midnight UTC), rejects bad input `ERR_QUANTITY_INVALID` (422), returns `{current_utc}` printed without fractional part on whole seconds — `implementation/utils.py:16-37,63-78`, `implementation/routes/clock.py:13-25`
- §3.1 — insert — ambiguity — suspension requires `ACTIVE` grower, else `ERR_INVALID_STATE` (409) — `implementation/routes/growers.py:66-78`
- §3.1 — insert — ambiguity — `committed_house_count` is a non-negative integer — `implementation/routes/contracts.py:42-46`
- §3.2 — insert — ambiguity — activation precondition failures (non-`DRAFT`, non-`ACTIVE` grower, insufficient houses) all surface `ERR_INVALID_STATE` (409) — `implementation/routes/contracts.py:75-102`
- §3.2 — insert — ambiguity — renewal request on non-`ACTIVE` contract or after `term_end_date` → `ERR_INVALID_STATE` (409) — `implementation/routes/contracts.py:115-135`
- §3.2 — insert — ambiguity — impose-upgrade allowed in any contract status and is a no-op when already set — `implementation/routes/contracts.py:105-112`
- §3.3 — insert — ambiguity — no house-occupancy check and no contract-belongs-to-house's-grower check at flock planning — `implementation/routes/flocks.py:57-88`
- §3.3 — insert — ambiguity — placement scheduling applies no flock-lifecycle check — `implementation/routes/flocks.py:113-140`
- §3.3 — insert — ambiguity — placement confirmation requires the flock still `PLANNED`, else `ERR_INVALID_STATE` (409) — `implementation/routes/placements.py:28-35`
- §3.3 — revise — mismatch — confirmation moves the house to `PLACED` also from `DOWNTIME` (not only `ACTIVE`), clearing `downtime_until` — `implementation/services/domain.py:397-402`
- §3.3 — insert — ambiguity — feed deliveries accepted in any flock status; `PLACED`→`GROWING` flip only from `PLACED` — `implementation/routes/flocks.py:153-176`, `implementation/services/domain.py:161-166`
- §3.3 — insert — ambiguity — mortality reports accepted in any flock status — `implementation/routes/flocks.py:189-224`
- §3.4 — insert — ambiguity — `FAIL` on already-`QUARANTINED` extends `downtime_until` to the later value; `FAIL` on `PLACED`/`DECOMMISSIONED` records the audit with no status/downtime change — `implementation/services/domain.py:468-491`
- §3.4 — revise — ambiguity — quarantine release requires a `PASS` dated on/after the house's most recent `FAIL` audit (not "the FAIL that triggered"); all failed release guards → `ERR_INVALID_STATE` (409) — `implementation/services/domain.py:507-530`, `implementation/routes/houses.py:75-130`
- §3.5 — insert — ambiguity — catch completion with zero weight tickets → `ERR_INVALID_STATE` (409) — `implementation/routes/schedules.py:27-33`
- §3.5 — insert — ambiguity — weight tickets accepted in any flock status; a post-harvest ticket recomputes `adj_fcr` and refreshes group averages — `implementation/routes/flocks.py:237-260`, `implementation/services/domain.py:176-183`
- §3.6 — insert — ambiguity — condemned loss on a non-`GROWING` flock → `ERR_INVALID_STATE` (409) — `implementation/routes/flocks.py:334-343`
- §3.7 — revise — mismatch — recompute-settlement allowed for any `HARVESTED` flock regardless of group status (was "while the group is OPEN"); `variant` assigned from group status (`PROVISIONAL` while `OPEN`, else `FINAL`); OCC token "accepts" per revised §2.7 — `implementation/routes/flocks.py:358-381`, `implementation/services/domain.py:323`
- §3.7 — revise — mismatch — group `LOCKED` is terminal; the API has no transition to a settled group status (was "reaches `SETTLED`"); also pins that lock recomputes only `PENDING` settlements, leaving `DISPUTED` untouched — `implementation/services/domain.py:562-577` (grep confirms no `SETTLED` group status anywhere)
- §3.8 — insert — ambiguity — ranking population is the scored members (`HARVESTED`+`SETTLED`, same as averages); final tie-break after score/weight/placed_date is earlier creation order — `implementation/services/domain.py:247-258,268-276`
- §3.8 — revise — ambiguity — repayment share uses the `recovery_pct` of the grower's oldest `ISSUED` loan (was singular "the loan's") — `implementation/services/domain.py:311-320`
- §3.9 — revise — mismatch — removed "A fully-cleared loan can also be moved to `CLOSED`" (no such transition exists); pins oldest-first waterfall tie-break by creation order — `implementation/services/domain.py:70-77,363-377` (grep confirms no `CLOSED` anywhere)
- §3.10 — insert — ambiguity — resolve-dispute also reassigns `variant` from the group's current status (`FINAL` once locked) — `implementation/routes/settlements.py:63-79`
- §4 preamble — insert — ambiguity — recompute-settlement returns `200 OK` even on first creation of the settlement row — `implementation/routes/flocks.py:379-381`
