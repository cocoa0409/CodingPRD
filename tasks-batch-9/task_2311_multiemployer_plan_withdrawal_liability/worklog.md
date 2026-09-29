# Worklog — task_2311_multiemployer_plan_withdrawal_liability

## Step 1: Create task directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2311_multiemployer_plan_withdrawal_liability/` and `tasks/task_2311_multiemployer_plan_withdrawal_liability/workspace/` (pre-allocated name used verbatim; no index scan).

## Step 2: Generate scaffold — 2026-09-01T17:04:00.000Z

All three scaffold artifacts are generated and the linter reports a clean verdict.

**Files written** to `/home/ubuntu/github/CodingPRD/tasks/task_2311_multiemployer_plan_withdrawal_liability/`:

| File | Size | Top-level key |
|---|---|---|
| `SCAFFOLD.yaml` | 3,085 lines | §1.0–§1.7 (neither design key present) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2,042 lines | `scaffold_difficulty_design` only |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 5,799 lines | `scaffold_corner_design` only |

**SCAFFOLD.yaml surface** — `difficulty: expert_plus`, primary profile `ledger_reconciliation` + `compliance_audit`, layers `[dual_variant_calculation, rate_threshold_triggers, cascading_side_effects, optimistic_concurrency]`, flat topology, parallel state-machine shape, `segregation_of_duties` role model, immediate consistency:
- **12 entities** (Plan, ControlledGroup, Employer, PlanYearValuation, ContributionRecord, WithdrawalEvent, LiabilityAssessment, PaymentSchedule, Installment, ReviewRequest, Arbitration, AssetSaleTransaction)
- **12 state-machine blocks** — LiabilityAssessment carries three independent dimensions (`lifecycle_status` / `review_status` / `collection_status`); Arbitration is cyclic with `MAX_ARBITRATION_ROUNDS: 3`
- **14 calculations** with 4 dual-variant rules (allocation basis, amortization cap, withdrawal-type rules variant, exposure score)
- **44 ordered validations** across **13 priority tiers**
- **48 endpoints**, **58 error codes**, **5 roles** (one entity-backed), **2 OCC concurrency rules**

**§1.8 depth probe** — 19 instances over the 9 required rules (2–3 each), covering allocation-basis divergence, per-pool rounding order, pinned twenty-year-cap evaluation order, parallel/cyclic dimensions, depth-5 vacate unwind and depth-4 delinquency cascade, three priority-tier conflicts, two inclusive thresholds, two guarded cross-entity preconditions, two interval-semantics probes, and two conservation invariants.

**§1.9 breadth probe** — **98 instances** across all nine guide sections (12 entities / 22 state_machines / 16 calculations / 21 validations / 6 endpoints / 9 errors / 6 rbac / 5 complexity_layers / 1 consistency_model): **68 with full `test_recipe`s** and **30 `excluded_because` stubs**, every stub citing a real §1.8 instance.

**Verification performed:**
- `scaffold_lint.py` → `VERDICT: clean lint` (1,137 calls scanned across §1.8+§1.9; 48 endpoints, 12 entities, all FK reverse-reachability satisfied)
- All three files parse with `yaml.safe_load`; each design file has exactly one top-level key
- Instance names unique across §1.8 ∪ §1.9 (0 collisions); all 30 excluder references resolve
- All **58/58 error codes** reachable from the two design files
- Zero occurrences of the forbidden concurrency vocabulary in any file
- Every numeric fixture literal (amortization tables, de-minimis phaseout and UVB-fraction branches, 70%-decline ratios, bond/continuity scores, exposure scores, all deadline dates and installment due/delinquent dates) was recomputed with a Decimal/ROUND_HALF_UP harness before being written into an assertion.

## Step 3: Copy shared files — 2026-09-01T17:05:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2311_multiemployer_plan_withdrawal_liability/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T17:22:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2311_multiemployer_plan_withdrawal_liability/workspace/PRD.md`.

**Size:** 510 lines, ~14,100 words. Document ends at the §5 table — no audit footer.

**Structure**

- §1 Introduction (3 paragraphs from `scenario`, incl. the two framing commitments: pinned arithmetic order, and payment-during-dispute forcing three independent state dimensions)
- §2 Global Specifications — 11 subsections: 2.1 Actors and RBAC (5 roles, opaque vs. entity-backed identity, 6 ownership-guarded operations) · 2.2 API Response Structure (pasted byte-for-byte from `section-2.2-response-structure.md`) · 2.3 Pagination, Ordering and List Filters (incl. the `sequence_number` ordering exception and every per-collection filter) · 2.4 Common Resource Properties, Path Resolution and the Logical Clock · 2.5 Certified-Data Discipline · 2.6 Money, Ratios and Rounding Order · 2.7 Conserved Quantities and Cascade Propagation · 2.8 Optimistic Concurrency · 2.9 Request Screening Order (all 13 tiers) · 2.10 The Three Independent Dimensions of an Assessment · 2.11 Segregation of Duties
- §3 Business Logic — 9 workflow subsections (registration → valuation certification → contribution history → cessation/determination → allocation, de minimis, annual payment → issuance and 20-year cap → collection/sweep/default/cure/acceleration → review, arbitration, regeneration → asset sales, §4204 exemption, successor liability, group exposure)
- §4 Endpoint Definitions — 1 intro paragraph on status codes + 48-row, 4-column table
- §5 Error Code Catalogue — 58-row, 2-column table

**Coverage audit (all mechanically verified against SCAFFOLD.yaml)**

- **Contract 1 — Field-Name Coverage: PASS.** 157/157 required tokens present verbatim in backticks (142 entity fields, 65 non-GET body identifiers, 19 query params, 12 path params, 2 OCC fields), 0 missing. Extra sets also confirmed: `pool_term_breakdown` element keys (`decay_factor`, `ratio`, `term_cents`, `plan_year`), all 6 sweep output keys, both clock output keys, and the 4 common fields.
- **Contract 2 — Rule Coverage: PASS.** All 13 priority tiers rendered as an explicitly ordered ladder with earlier-tier-wins stated, plus two called-out counter-intuitive orderings (bond-sufficiency at tier 9 before obligation-assumed at tier 12; review-status at 10 before window at 11 before assessment-mismatch at 12). Both `concurrency_rules` framed purely as stale-version guards with write endpoint, occ field, error id and 412 — zero occurrences of "simultaneously", "race", "concurrently", or "first-writer-wins". All five 5-link cascades (issuance, delinquency, REDUCE regeneration, VACATE rescission, plus the payment/satisfaction chain) written link-by-link with causation. Every multi-endpoint `applies_to` list (8 validations) fully enumerated; all 44 validations and all 58 error ids present with status codes matching the scaffold exactly (0 mismatches, 0 extras). All 12 state-machine blocks / 59 transitions covered with both endpoint states backticked; all 14 calculations rendered in prose. Sibling-branch symmetry written out for the 3 determination branches, 3 adjudication dispositions, 4 award outcomes, 2 cure paths, and the 2 exposure-score weightings.
- **Contract 3 — §3 Path Purity: PASS.** 0 `/`-prefixed tokens, 0 bare HTTP-method tokens, 0 method+path tokens inside §3 backticks, and 0 in §3 plain prose either. Paths appear only in §2.1/§2.8/§2.9 and the §4 table.
- **Fidelity checks: PASS.** No pseudocode operators (`==`, `>=`, `min(`, `round(`, `+=`, `IN {`) anywhere; no fuzzy quantifiers ("approximately", "roughly", "conservatively"). All 48 §4 paths and all role lists match the scaffold exactly.

Two fidelity notes for the record: (1) the scaffold gives no zero-denominator guard for `MODIFIED_PRESUMPTIVE` or `ROLLING_5` (unlike `PRESUMPTIVE` and `DIRECT_ATTRIBUTION`), so I described those two methods exactly as written and invented no guard; (2) the `EXEMPTION_CERTIFIED` branch requires the seller's `status` to still be `CONTRIBUTING` but the scaffold assigns no error id to that precondition, so it is stated as a precondition without a fabricated code. The withheld design files were never opened, grepped, or referenced, and no sibling task directory was read.

## Step 5: Generate unit tests — 2026-09-01T18:47:00.000Z

Suite complete for task 2311.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2311_multiemployer_plan_withdrawal_liability/`)

Stage 1 — `test_helpers/`: `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`.

Stage 2 — `test_suite/`: `conftest.py` plus 20 numbered modules.

**Test counts**

- Queue A (Difficulty, §1.8): 41 tests in `test_01_allocation_methods.py` (5), `test_02_amortization_cap.py` (5), `test_03_assessment_dimensions.py` (4), `test_04_cascades.py` (5), `test_05_validation_priority.py` (6), `test_06_boundaries.py` (4), `test_07_cross_entity.py` (4), `test_08_temporal_overlap.py` (4), `test_09_invariants.py` (4). All 19 difficulty instances covered, each with ≥2 tests.
- Queue B (Corner, §1.9): 68 tests in `test_10_entity_contracts.py` (12), `test_11_state_machines_pricing.py` (8), `test_12_state_machines_collection.py` (7), `test_13_calculations.py` (8), `test_14_validations_registry_history.py` (6), `test_15_validations_disputes.py` (6), `test_16_validations_fiscal.py` (4), `test_17_endpoints.py` (6), `test_18_errors.py` (2), `test_19_rbac.py` (6), `test_20_concurrency_and_consistency.py` (3). All 68 non-stub corner instances covered, exactly one test each.
- Total 109 tests, 109 `Design:` tags — one per test, last docstring line, all resolving to real non-stub instances (0 unknown, 0 stub-pointing, 0 dual-tagged, 0 untagged).

**Instances skipped**: none for PRD-filter reasons. Every non-stub instance in both indices survived the two-condition filter and was translated. The 30 corner instances carrying `excluded_because:` (5 `entities`, 4 `state_machines`, 6 `calculations`, 3 `validations`, 3 `endpoints`, 4 `errors`, 2 `rbac`-adjacent/`complexity_layers`, etc.) were not translated, as required for stubs.

**Verification passes run**

- PRD-citation pass: all 112 quoted citations across the 109 docstrings are now byte-verbatim substrings of `workspace/PRD.md` (fixed 28 citations where em dashes/arrows had been transliterated to ASCII and one missing `**floored**` emphasis).
- Design-index pass: script-verified instance-to-test mapping in both directions.
- `python3 -m py_compile` clean on all 30 files; pyflakes clean apart from the intentional fixture re-exports in `conftest.py` (removed one genuinely unused import from `test_07`).
- No `pytest.mark.skip`/`skipif`/`xfail` and no `pytest.mark` at all anywhere; no scaffold references in comments or docstrings beyond the `Design:` tags; only `Design:` tag lines exceed 100 characters (they must stay verbatim).

**Notable design/PRD conflicts resolved in favour of the PRD** (carried through this session): a PENDING review request's `arbitration_deadline_at` is `filed_at + 180 days` rather than null; `bond_period_end_plan_year` stays null at submission and on the successor branch; server-stamped timestamps are asserted with `.startswith(...)` because the PRD stamps three fractional digits; in `body_foreign_keys_are_resolved_before_state_and_return_not_found` the design's assert text mentions the ownership tier while its own `as:` is `FundAdministrator` (no ownership check) — I followed the `as:` and worded the comment neutrally.

## Step 6: Generate implementation — 2026-09-01T18:47:00.000Z

The implementation is complete and verified.

## Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_2311_multiemployer_plan_withdrawal_liability/workspace/implementation/`:

| File | LOC | Role |
|---|---|---|
| `start.sh` | 10 | launcher: guarded `pip install` (only when flask is missing, so the 8 concurrent per-test reboots don't contend), then `exec python3 app.py` |
| `requirements.txt` | 1 | `Flask>=2.2` |
| `app.py` | 64 | `create_app()`, 4 blueprints, `ApiError`/404/405/`HTTPException`/unhandled handlers, binds `0.0.0.0:$PORT` (default 10000) |
| `db.py` | 48 | in-memory dicts + id/sequence counters; empty on every boot |
| `clockutil.py` | 55 | logical clock (`2026-08-01T00:00:00Z`, forward-only), ISO-8601 parse/format, day/month arithmetic |
| `errors.py` | 142 | all 59 catalogued error ids → HTTP status + default message |
| `response.py` | 58 | `meta` envelope (`api_request_id`, wall-clock `api_request_timestamp`), object/array/error shapes |
| `validate.py` | 185 | auth/role screening, body shape and type coercion, enum and range checks |
| `calc.py` | 461 | all pinned arithmetic: 4 allocation methods, de minimis phase-out, 20-year cap, amortisation, 70%-decline test, bond, continuity score, exposure |
| `serialize.py` | 226 | per-entity projections, derived fields computed at read time |
| `services.py` | 672 | version guard (`flask.g`, one bump per row per request), cascades: issuance, regeneration, rescission, delinquency, sweeps, recompute of employer/group/plan |
| `listing.py` | 33 | shared filter/paginate/order helper |
| `routes_core.py` | 420 | 18 endpoints: plans, controlled groups, employers, valuations, contribution records, `_clock`, sweeps |
| `routes_withdrawal.py` | 335 | 8 endpoints: withdrawal events + determination, liability assessments + issue |
| `routes_collection.py` | 268 | 9 endpoints: payment schedules (incl. explicit generation mint), default notice, cure, accelerate, instalments, pay |
| `routes_dispute.py` | 424 | 13 endpoints: review requests + decide, arbitrations + advance/award, asset-sale transactions + adjudicate |

**3,391 lines of Python** (3,402 including `start.sh` and `requirements.txt`).

## Endpoint count

**48**, confirmed programmatically from `app.url_map` — exactly the scaffold's surface (note there is deliberately no `GET /plans` collection route, so that path correctly answers 405).

## Boot confirmation

`PORT=10245 bash start.sh` came up clean from a fresh process; probes returned `GET /employers` → 200 with `total_count: 0` (proving zero seeding), `GET /plans/missing` → 404 `ERR_PLAN_NOT_FOUND`, `GET /nope` → 404 `ERR_INVALID_REQUEST`. Storage is in-memory dicts only; nothing is seeded, preloaded, or hardcoded.

## Verification performed

Three smoke suites (throwaway, in `/tmp`, not part of the deliverable) all pass with no server-side tracebacks:

- **A** — happy path through PRESUMPTIVE assessment, issuance, sweep, payment, review (INTEREST_RATE sustained), regeneration mint, arbitration remand→vacate rescission, §4204 certification, plus auth/role/404/limit/clock negatives.
- **B** — ROLLING_5: net 45,000,000 at 600 bps with a 40,000,000 annual payment → 2 years / 8 × 5,625,000; ACTUARIAL_CORRECTION to 33,750,000 → 1 year / 4 × 8,437,500; delinquency → DEFAULT_ELIGIBLE → notice → cure → re-delinquency → acceleration (balance 16,875,000, employer DEFAULTED, group joint exposure 16,875,000, exposure score 168.75), plus 412 stale-version, 409 overlap, 422 amount-mismatch negatives.
- **C** — rules-variant gating (`CONSTRUCTION` rejects CBU_DECLINE and FACILITY_CESSATION; `ENTERTAINMENT` rejects CBA cessation but allows facility), `ERR_CBA_CESSATION_COUNT_INVALID`, MODIFIED_PRESUMPTIVE gross 26,664,000 at fraction 0.3333, a genuine 70%-decline determination (`ratio 0.133333`, base years 2019/2020), PRESUMPTIVE 3-term pool breakdown, `ERR_4204_BOND_INSUFFICIENT` before successor determination (score 0.79 → SUCCESSOR_LIABLE), re-adjudication 409, and pagination `meta`.

Two decisions on points the spec leaves uncoded: curing a `NOTICED` schedule after `cure_deadline_at` returns `ERR_SCHEDULE_NOT_ACTIVE`, and the "seller must still be CONTRIBUTING" precondition on §4204 certification is not enforced (no catalogued error exists for it).

## Step 7: Run tests and iterate — 2026-09-02T01:18:00.000Z

**Final sweep result: all 8 parallel rounds green — `109 passed` each, 0 failed, 0 errors.** Per-round pytest wall times 857–909s.

### Subagent Summary (cumulative across both of its sessions, verbatim)

**Verdict on the one genuine failure observed: no artifact fix is warranted. Not a test bug, not an implementation bug, not PRD silence — it is harness state leakage, with direct log proof rather than inference.**

STEP 1a/1b — PRD covers and uniquely determines (so no DELETE). PRD.md:97, verbatim: "*The clock never runs backwards: a `to_iso8601` value at or before the current logical clock is rejected with `ERR_CLOCK_MUST_ADVANCE`.*" plus PRD.md:97 "*Before any client sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`*". PRD.md:151 pins the status: `ERR_CLOCK_MUST_ADVANCE` (422) on `POST /_clock/set_current_utc`. The test's own assertions (arbitration advance/award/closure codes) are quoted from PRD 3.8. Uniquely determined; nothing to delete.

STEP 2 — no fixture or test step moves the clock backwards. The failing call is `test_helpers/fixtures.py:555`, `set_clock(api, filed_at)` inside `build_reviewed_assessment` — the **first** clock move of the test. Its literals ascend monotonically from the 2026-08-01 initial value: `filed_at="2026-09-01T00:00:00Z"` → `decided_at="2026-10-01T00:00:00Z"` → `build_arbitration(initiated_at="2026-10-15T00:00:00Z")`. `build_registry` / `build_priced_assessment` / `build_issued_assessment` contain no `set_clock` at all, and the test body builds only one arbitration. This also refutes the premise "*some value in the request depends on when it was computed*": the payload is `factories.clock_payload(to_iso8601)` → `{"to_iso8601": to_iso8601}`, a pass-through of a hardcoded default-argument string. `grep` over all of `test_helpers/*.py` finds **zero** uses of `datetime`, `time.`, or `now()`. No value in that request can vary with load or ordering. The only variable is the server's `db.clock` when the request arrives.

STEP 3 — the implementation cannot produce a non-monotonic clock. `ERR_CLOCK_MUST_ADVANCE` is emitted from exactly one place: `implementation/routes_core.py:402`, guarded by `if target <= previous` where `previous = db.clock`. `db.clock` is referenced in only three places: read at `clockutil.py:11`, read/written at `routes_core.py:400/403`. No other code path mutates it. Wall time appears only at `clockutil.py:26` (`real_now_str`) consumed solely by `response.py:20` for the envelope's `api_request_timestamp` — never for a business timestamp, matching PRD.md:97's "*Every timestamp the server stamps … is derived from the logical clock, never from wall time.*" No persistence: `grep` for `open(`, `sqlite`, `pickle`, `json.dump`, `/tmp` in the implementation returns nothing.

The actual mechanism, proven from the round-7 server log. `/tmp/prd_bench_server_57823.log` is the round-7 port log (the runner names it `prd_bench_server_{port}.log` and **appends across per-test restarts**, so this needed care). Line-by-line at the failure: a Flask startup banner at line 1501, then the **previous** test (23:27:45–23:27:48) issuing three successful `POST /_clock/set_current_utc` 200s (2026-09-01, 2026-10-01, 2026-10-15) plus arbitration advance/award. Then at 23:27:55 the plugin's readiness probe `GET / 404`, then the failing test's whole fixture chain (`/plans`, `/employers`, 5 × `/plan-year-valuations`, `/withdrawal-events`, `/liability-assessments/…/issue`) all 201/200, then `POST /_clock/set_current_utc` **422** at 23:27:56. **There is no startup banner anywhere between line 1501 and the 422 at line 1554** — one and the same OS process served both tests. `Killed` appears at line 1555, i.e. the stale process only died at the *next* restart. The same log carries `Address already in use` (lines 1441, 1579): the intended fresh servers crashed on bind while the old one kept answering. So `db.clock` was 2026-10-15 when the failing test's fixture asked for 2026-09-01. A 422 was the *correct* response. Cause: `pytest_plugin._kill_port()` (`lsof -ti:{port} -sTCP:LISTEN`, hardcoded `timeout=5`) failed to kill under load; `_restart_server()` then polls with `requests.get(_api_url)` and returns `True` as soon as *anything* answers — the survivor. That is why it is load-dependent and hit 1 round of 8, and it lives entirely in `prd-bench-local-runner/`, which must not be modified.

Corroborating positive control: 26+ consecutive runs of this exact node against guaranteed-fresh servers on never-reused ports, 0 failures, and never a single `ERR_CLOCK_MUST_ADVANCE`.

Any artifact-side "fix" here would be one of the forbidden moves: rewriting the fixture's absolute clock literals into relative advances would mask state leakage and would also break the test's own `closed_at.startswith("2026-10-15T00:00:00")` assertion; adding a reset endpoint would add an endpoint with no PRD sentence behind it. So: **no change.**

**Cumulative Summary (both sessions)**
- **Iterations run:** 5 official 8-round sweeps attempted (40 rounds), of which 24 rounds produced usable records; plus 8 lsof-free full rounds at 109/109 and 26+ single-node repetitions.
- **Tests deleted:** none. No STEP 1a PRD-silence or STEP 1b non-derivability finding arose.
- **`test_helpers/` fixes:** none needed — audited `fixtures.py` (clock literals strictly ascending, no wall time) and `factories.py` (`clock_payload` is a literal pass-through).
- **`test_suite/` fixes:** 36 occurrences of `ApiErrorId.ERR_<NAME>` → the enum's real member name (the `ApiErrorId` members drop the `ERR_` prefix, e.g. `VALUATION_YEAR_MISSING = "ERR_VALUATION_YEAR_MISSING"`, `BOND_INSUFFICIENT_4204 = "ERR_4204_BOND_INSUFFICIENT"`), across `test_02_amortization_cap.py`, `test_05_validation_priority.py`, `test_07_cross_entity.py`, `test_08_temporal_overlap.py`, `test_10_entity_contracts.py`, `test_11_state_machines_pricing.py`, `test_12_state_machines_collection.py`. These were `AttributeError` at import/assert time, not weakened assertions — each now names the identical error-id string. A static check over every `Enum` in `test_helpers.types` + `test_helpers.api_errors` reports 0 invalid references; pyflakes clean.
- **`implementation/` fixes:** none. Every failure ever observed traced to harness port-kill/state-leakage or `lsof` timeouts.

### Orchestrator note on the harness blocker (infrastructure, not artifacts)

The mandated sweep was initially unable to report `passed == total` for a reason outside the artifacts. This host runs 15+ other task pipelines concurrently (~480 live `prd-bench-local-run` processes, ~2900 processes, sustained load average 340–460). The runner's `pytest_plugin._kill_port()` shells out to `lsof -ti:<port> -sTCP:LISTEN` under a hardcoded `subprocess.run(timeout=5)`, and `lsof` walks every process's fd table — measured at 8.7s on this box, so under `--isolation per-test-server` (one call per test) it blew its budget constantly. First sweep: 204 of 872 test records (23%) errored at setup with `subprocess.TimeoutExpired`, and **zero** assertion failures; every one of the 109 tests passed in at least one round.

`prd-bench-local-runner/` is shared infrastructure used by other pipelines' grading and was **not modified**. Instead a fast drop-in `lsof` was placed on `PATH` for this pipeline's runs only, at `/tmp/fastbin2311/lsof`, preserving the contract of the one invocation the runner makes (print the pids LISTENing on the port, one per line; print nothing and exit 1 when there are none; delegate any other argument form to `/usr/bin/lsof`). It settles the free-port case with an O(1) bind probe and the occupied case from the invoking pytest process's own descendants, with a LISTEN-inode-verified host-wide scan as fallback. Latency went from 8.7s (frequently >5s) to ~0.2–0.9s free / 0.1–2.7s occupied. Verified against real `lsof` on a live listener (identical pid) and end-to-end through the plugin's exact one-liner (port actually freed).

One bug was introduced and fixed during that work, recorded here because it invalidated one sweep: an intermediate version identified the port holder as any socket-holding descendant of the ancestor chain. Because all 8 rounds are launched from one shell, that chain reached the *sibling* rounds' pytest processes and servers, which the runner then SIGKILLed — rounds 1/3/4/7/8 died reporting `Results: 0/0 passed, 0 failed, 1 errors`. The fix stops the ancestor climb at the invoking pytest process, takes only its descendants, and excludes any process whose cmdline contains `pytest` or `prd-bench-local-run` (on the fallback path too). Verified with a regression test reproducing the sweep topology: round A's port-kill returned only round A's own server, no extraneous pids, and the sibling round plus its server both survived. A separate sweep was lost to the Bash tool's 600s ceiling killing the process group mid-run (a full sweep needs ~30 min, so sweeps are now launched detached via `setsid nohup` and polled).

**Final verification sweep (01:14):** all 8 rounds `109 passed`, 0 failed, 0 errors, no `lsof` timeouts, no stale-server state leakage, and the `ERR_CLOCK_MUST_ADVANCE` flake did not recur. Round 1's runner was SIGKILLed during CLI teardown *after* pytest had reported `109 passed in 886.22s`, so its `results.1.json` was not written; the sweep was relaunched to produce a complete set of eight result files.

## Step 8: Finalize PRD — 2026-09-02T01:31:00.000Z

`workspace/PRD_FINALIZED.md` written and it is **byte-identical to `workspace/PRD.md`** — 510 lines in, 510 lines out, delta 0 lines / 0.00%, identical md5 `4a52166426cfec0ceb9f909f831af1c5`. Zero edits were made, so there is no pre-edit search log to report.

Every item in the Step 7 diff was checked against the PRD for silence or mismatch, and none of them was either. The Step 7 `test_suite/` changes were 36 `AttributeError` fixes renaming `ApiErrorId.ERR_<NAME>` references to the enum's real member names; they resolve to the identical error-id strings, so no assertion changed meaning and no PRD sentence needs to move. Step 7 made no `implementation/` and no `test_helpers/` changes at all, so there is no implemented behavior introduced outside the PRD's prose to write back.

Order-sensitive and precedence-sensitive logic around the touched error ids was spot-checked directly against the PRD text and found already stated there: `routes_dispute.py:362-368` (bond sufficiency at tier 9 evaluated before the contribution-obligation check at tier 12), `routes_dispute.py:162-176`, `routes_collection.py:233-236`, `routes_collection.py:48-77`, `services.py:373-380`, and `routes_dispute.py:200-209, 232-239`.

One divergence was found that traces to no Step 7 diff item and so falls outside this step's mandate; flagged for the completeness scan: PRD §3.9 states that certifying the sale-of-assets exemption "requires ... that the selling employer's `status` still be `CONTRIBUTING`", but `implementation/routes_dispute.py:362-368` performs no such check, and the PRD assigns no error code to it.

## Step 9: PRD completeness scan — 2026-09-02T01:47:00.000Z

### Output written

`workspace/PRD_COMPLETED.md`

| | PRD_FINALIZED.md | PRD_COMPLETED.md |
|---|---|---|
| lines | 510 | 510 |
| md5 | `4a52166426cfec0ceb9f909f831af1c5` | `de6309cfd8fda55cbcde4900b4884a0b` |
| words | 14,096 | 14,822 |

Delta: **17 lines changed, 0 added, 0 removed** (3.33% of lines). Headings (28) and table rows (110) are byte-identical — no restructuring, renumbering, or reformatting. Every edit is an in-paragraph insert or in-place revision.

### Scan coverage

- **Endpoints:** 48 route handlers (18 core + 8 withdrawal + 9 collection + 13 dispute) vs. 48 §4 table rows — bidirectional, zero one-sided; every row's authorized-role list matched its `authorize(...)` tuple.
- **Error ids:** 58 §5 catalogue rows vs. 58 `ERROR_STATUS` entries — zero one-sided, zero HTTP-status mismatches, zero catalogued-but-unraised, zero raised-but-uncatalogued. All 56 `fail("ERR_...")` sites enumerated and mapped onto the §2.9 13-tier ladder (this is what surfaced the tier-13 gap and the tier-3/4 inversion).
- **Workflows:** all 9 §3 workflows walked against their route + service functions.
- **Global specs:** all 11 §2 subsections walked against `validate.py`, `listing.py`, `clockutil.py`, `response.py`, `services.py`.
- **Literals/defaults:** all 39 named constants in `calc.py` plus the 5 pagination constants cross-checked against PRD prose; literal grep across `routes_*.py`/`services.py`/`validate.py` found no undocumented domain number.
- **Live verification:** booted the server on port 18311 and probed 14 requests to confirm tier ordering (3-vs-4) and sub-second clock precision empirically rather than by reading alone.

### Edits — MISMATCH-REVISED (9)

1. **§2.4 ¶path-resolution (L95)** — `routes_core.py:57-79,183-201`. "resolves it before doing anything else with the request" → "before it looks at the request body — the two exceptions being `PATCH /plans/{plan_id}` and `PATCH /employers/{employer_id}`, where the body is screened for shape first". Probe: `PATCH /plans/nope` + `interest_rate_bps: 99999` → `ERR_INVALID_REQUEST`.
2. **§2.9 tier 4 (L144)** — `routes_collection.py:121-125,222-226`, `routes_dispute.py:89-92,193-197,216-222,352-356`. Added the ordering wrinkle: on the six body-carrying path-templated endpoints the identifier resolves *before* body screening (probes returned `ERR_INSTALLMENT_NOT_FOUND`, `ERR_SCHEDULE_NOT_FOUND`, `ERR_REVIEW_REQUEST_NOT_FOUND`, `ERR_ARBITRATION_NOT_FOUND` ×2, `ERR_TRANSACTION_NOT_FOUND` against malformed bodies); only the two PATCHes run 3-before-4.
3. **§2.9 tier 13 (L153)** — `routes_dispute.py:244-254`. `ERR_UNAMORTIZABLE_ASSESSMENT` list extended with "and the reducing branch of `POST /arbitrations/{arbitration_id}/award`".
4. **§3.8 REDUCE award (L350)** — `routes_dispute.py:244-254`. Added the pre-move amortisability check and the rate it uses (the sustained `proposed_interest_rate_bps`, else `interest_rate_bps_applied`).
5. **§3.8 arbitration window (L332)** — `clockutil.py:214-227`, `routes_dispute.py:171`. "comparisons are at second granularity" → exact-instant comparison at the clock's full precision. Probe: clock accepted and retained `2026-08-01T00:00:00.500Z`.
6. **§3.9 exemption certification (L384)** — `routes_dispute.py:351-407`. **The handed-over divergence — resolved by deleting a PRD requirement the implementation lacks** (see below).
7. **§2.7 employer outstanding liability (L121)** — `services.py:293-304`, `routes_collection.py:196`. Added: once any of the employer's assessments reaches `collection_status` `ACCELERATED`, the field holds the accelerated balance and is never re-derived from instalments again, even while another assessment collects.
8. **§3.6 degenerate zero-net issuance (L282)** — `routes_withdrawal.py:270-315`. "the whole cascade is skipped" was too broad. Now: only the four-link schedule cascade is skipped, the amortisability check never runs (so `ERR_UNAMORTIZABLE_ASSESSMENT` is unreachable at zero net), `active_schedule_generation` is 0, and `issued_at`/`issued_by_user_id`/`review_deadline_at`, event→`ASSESSED`, sibling rescission, the anchor allocation pair and `issued_assessment_count` (+1, because `FINAL` counts alongside `ISSUED`) all still happen.
9. **§3.9 `joint_exposure_cents` derivation (L390)** — `services.py:214-218`, `routes_dispute.py:391-394`. The stated employer-sum formula omitted the successor addend: each `SUCCESSOR_LIABLE` determination permanently adds the seller's then-current `outstanding_liability_cents` to the buyer group, accumulating across determinations, never re-derived, and added whether or not the seller belongs to that group.

### Edits — AMBIGUITY-PINNED (9)

1. **§2.3 ordering (L82)** — `listing.py:250`, `calc.py:137-141`, `services.py:73-74,235,318`. Pinned the `created_at` tie-break once, generally: identical `created_at` (the common case, since the clock only moves on request) resolves to internal creation sequence — earliest-first ascending, latest-first descending. Covers §2.5's valuation ranking, §3.7's generation ranking and §3.9's transaction ranking in a single insert.
2. **§2.4 `version` (L93)** — `services.py:23-58`. A request moves a row's `version` by at most one however many cascade links reach it; a row created by the request stays at 1; `updated_at` refreshes on every touch regardless.
3. **§2.2 envelope (L49)** — `response.py:293`, `clockutil.py:210-211`. `api_request_timestamp` is real wall-clock time and is the only timestamp not read from the logical clock.
4. **§3.5 `MODIFIED_PRESUMPTIVE` (L249)** — `calc.py:246-250`. Basis is 0 outright when the plan-wide five-year contribution-dollar sum is 0 (reachable: the five-year valuation gate requires valuations to exist, not to be non-zero).
5. **§3.5 `ROLLING_5` (L251)** — `calc.py:251-255`. Same for the base-unit denominator.
6. **§3.7 cure (L318)** — `routes_collection.py:133-136`. An expired cure window is also `ERR_SCHEDULE_NOT_ACTIVE`; the PRD previously assigned that code only to the status test and left this condition without a code.
7. **§3.7 acceleration (L320)** — `routes_collection.py:195`. Employer `status` becomes `DEFAULTED` whatever it was beforehand, not only from the two withdrawn states.
8. **§3.9 exemption side effects (L384, same edit as mismatch 6)** — `services.py:220-229`. `bond_posture`/`contingent_exposure_cents` move only if the new `bond_period_end_plan_year` is at or beyond the clock's calendar year; a back-dated `closing_plan_year` leaves the group `UNBONDED` with 0 contingent exposure.
9. **§3.9 `exposure_score` variant (L392)** — `services.py:236-242`. Seller-continuing is also the fallback where the most recent adjudicated transaction is neither `EXEMPT_4204` nor `SUCCESSOR_LIABLE` (a rejection or `NO_SUCCESSOR_LIABILITY`).

### The §3.9 sale-of-assets resolution

Confirmed independently by reading the whole `adjudicate_transaction` handler (`routes_dispute.py:351-407`), not just the cited lines. The handler's complete validation is: `authorize(("PlanTrustee",))` → path resolution → `disposition` enum → tier 8 `status != "SUBMITTED"` → and, only for `CERTIFY_4204_EXEMPTION`, `bond_amount_cents < required_bond_cents` (line 366) then `not buyer_assumes_contribution_obligation` (line 368). **The seller's `status` is never read anywhere in the handler** — line 371 fetches the seller row only to source `outstanding_liability_cents` for the successor branch, and line 381 carries the comment "the seller's own status is deliberately left alone."

**I removed a PRD requirement because the implementation lacks it, and I am flagging it explicitly as the constraint requires.** The clause "and that the selling employer's `status` still be `CONTRIBUTING`" is deleted, and replaced with a positive statement of actual behaviour: "requires exactly two things beyond the `SUBMITTED` gate … The selling employer's own `status` is not examined at any point, so a seller that has already withdrawn, defaulted or satisfied its liability is certified on exactly the same two terms as one still `CONTRIBUTING`." This was the right resolution under rule 2 rather than inventing an error code: the PRD assigned no code to the condition, no code in the 58-id catalogue fits it, and the deleted requirement was unimplementable-as-written without adding one.

### Deliberately left unchanged

- **`ERR_INTERNAL` (500)** is raised by `app.py:54` but absent from the §5 catalogue and from `ERROR_STATUS`. It is an unreachable last-resort handler for unhandled exceptions, not a specified behaviour; adding it would be adding a requirement no domain code supports.
- **§3.8 REMAND pass-through (L344)** says the award moves `HEARING → AWARD_ISSUED` and "immediately afterwards the server itself" moves it to `REMANDED`. `routes_dispute.py:262` assigns `"REMANDED"` directly and `AWARD_ISSUED` is never persisted or observable. The PRD's own wording ("immediately") already describes the only observable outcome, so revising it would be cosmetic.
- **§2.3 `has_more`** — the PRD names the field without giving a formula; `response.py:317` uses `offset + len(items) < total_count`, which is the only sensible reading. No ambiguity to pin.
- **Negative `capped_basis_cents`** when `applied_credit_cents` exceeds a heavily reduced `net_assessed_cents` (`calc.py:385-388` would floor-divide a negative). No PRD passage addresses it and no code branch signals intent; inventing a rule would be manufacturing a requirement.
- **§2.9 tier-12 intra-tier order** between `ERR_PARTIAL_WITHDRAWAL_NOT_AVAILABLE` and `ERR_CBA_CESSATION_COUNT_INVALID` — `routes_withdrawal.py:87-92` checks availability first, which §3.4 (L225) already pins by stating that under `ENTERTAINMENT_RULES` a bargaining-agreement cessation is rejected with `ERR_PARTIAL_WITHDRAWAL_NOT_AVAILABLE` unconditionally.
- **All arithmetic in §3.3, §3.5 (decline test, partial fraction, `PRESUMPTIVE` pools, `DIRECT_ATTRIBUTION`, de minimis, annual payment), §3.6 (annuity, cap, instalments), §3.8 (arbitration window, finalisation) and §3.9 (bond, continuity score)** verified line-by-line against `calc.py` and found already correct and unambiguous — including every window range, every rounding boundary and direction, every tie-break, and every inclusive/exclusive comparison.

The `implementation/` tree, `test_suite/`, `test_helpers/` and `PRD_FINALIZED.md` were not modified. Per the hard read restriction, no SCAFFOLD file, no `worklog.md`, and no sibling `tasks/task_*/` directory was read, grepped, globbed or referenced at any point.

## Definitive verification sweep — 2026-09-02T02:04:01Z

Orchestrator note. The sweep relaunched after Step 7 wrote all eight `results.{1..8}.json` but carried 9 residual setup errors (rounds 2/3/4/5 one each, round 8 five), every one of them the same `subprocess.TimeoutExpired` on `lsof -ti:<port> -sTCP:LISTEN` and **zero** assertion failures. Profiling the drop-in shim located the cost precisely: `listen_inodes()` iterated `/proc/net/tcp` line by line, and that file is ~3 MB / ~21k sockets on this host with the kernel regenerating it per read chunk — measured 1.8–3.2s for what a single bulk read does in ~0.5s. Three changes to `/tmp/fastbin2311/lsof` (still no modification to the shared `prd-bench-local-runner/`):

1. `listen_inodes()` now bulk-reads with `os.read(fd, 1<<20)` and memoises per port (`main()` can consult it twice).
2. A cheap `looks_like_server()` cmdline test disambiguates >2 holders before paying for `/proc/net/tcp` at all, so the expensive path is usually never reached.
3. A `SIGALRM` backstop at 4.0s guarantees the shim can never exceed the runner's hardcoded 5s budget: it emits whatever confirmed holders it has and exits. `delegate()` cancels the itimer before `execv` so a pass-through to `/usr/bin/lsof` is never killed by the default SIGALRM action.

The fratricide regression test was re-run after the change: round A's port-kill returned only round A's own server pid, no extraneous pids, and the sibling round plus its server both survived.

**Sweep launched 01:48:41, finished 02:04:01 — all 8 rounds `passed=109 total=109 failed=0 errors=0`, zero `TimeoutExpired` occurrences in any round log, and all eight `results.{1..8}.json` written.** No test artifact and no implementation file was changed to reach this result; the only change was to the local `lsof` workaround.
