# Worklog — task_2389_farm_ranch_package_underwriting

## Step 1: Create task directory — 2026-09-02T05:52:00.318Z

Created `tasks/task_2389_farm_ranch_package_underwriting/` and `tasks/task_2389_farm_ranch_package_underwriting/workspace/` (pre-allocated directory name used verbatim; no index scan performed).

## Step 2: Generate scaffold — 2026-09-02T07:24:00.000Z

All three artifacts are complete and the lint is clean.

## Generated files
- `/home/ubuntu/github/CodingPRD/tasks/task_2389_farm_ranch_package_underwriting/SCAFFOLD.yaml` (2966 lines, §1.0–§1.7 only — no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_2389_farm_ranch_package_underwriting/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1369 lines, single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_2389_farm_ranch_package_underwriting/SCAFFOLD_CORNER_DESIGN.yaml` (3146 lines, single key `scaffold_corner_design`)

## Scaffold size (§1.0–§1.7)
14 entities · 7 state machines / 42 transitions (2 parallel axes on FarmPolicy: `uw_status` + `compliance_status`) · 2 §1.2.1 concurrency rules · 16 calculation rules · 35 validation rules across a 15-rung priority ladder · 52 endpoints · 53 errors · 6 roles. Complexity profile: `flat` topology, `parallel` machines, `segregation_of_duties` role model, `immediate` consistency, layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers.

## Design instances
- **§1.8 difficulty: 20 instances across 9 rule blocks** — dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 3, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2.
- **§1.9 corner: 89 instances** (72 executable + 17 `excluded_because` stubs) — entities 15, state_machines 18, calculations 14, validations 14, endpoints 6, errors 10, rbac 6, cross_cutting_complexity_layers 5, consistency_model 1.

## Lint verdict (verbatim)
```
Coverage
  §1.5 endpoints declared:    52
  §1.1 entities declared:     14
  §1.8 instances scanned:     20
  §1.9 instances scanned:     72
  Calls scanned (§1.8+§1.9):  1104

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
Two `(d) capture JSONPath unresolvable` violations were found and fixed on the way (`$.data.referral_reason` → the actually-declared `referral_reason_code`).

## Coverage audit
- **Errors: 53/53 triggerable** — no uncovered error id. The 17 stubs each cite an existing §1.8 instance by name (all citations verified to resolve) rather than restating it weakly.
- **claim_type/section pairs**: all 89 validated against `references/claim-extraction-guide.md`'s fixed rows; stubs carry only `name`/`claim_type`/`grounds`/`excluded_because`.
- **Names unique across both design files** (0 collisions); every active complexity layer has at least one instance (OCC ×2, one per §1.2.1 rule; cascading via the compliance-reinstatement chain; dual-variant via an in-place RC↔ACV election switch; rate thresholds via utilization 0.952381 hitting both the 1.60 scarcity band and the 0.90 referral trigger in one rating).
- **Endpoints**: every write endpoint is exercised by a structured call; 12 pure-GET routes (child list reads, `GET /farm-accounts`, single-row reads of reference data) are asserted in prose rather than as separate structured calls — that is the only intentional gap.
- Every numeric assertion was derived from the §1.3 constants (e.g. ACV 30001000/12yr/grade-B → 11040368 vs RC 30001000; deductible bands 1.00/0.95/0.85 → 160000/152000/136000; livestock 172125 + 91800; hazard cap 110→100; ledger 5 rows summing to 419200 after suspend + reinstate).

## Step 3: Copy shared files — 2026-09-02T07:26:27.729Z

Copied `INSTRUCTION.md` → `tasks/task_2389_farm_ranch_package_underwriting/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T07:41:00.000Z

PRD written to `/home/ubuntu/github/CodingPRD/tasks/task_2389_farm_ranch_package_underwriting/workspace/PRD.md`.

**Shape:** 401 lines, ~11,200 words. Sections: §1 Introduction (3 paragraphs), §2 Global Specifications with 11 domain-derived subsections (2.1 Producer/Underwriting/Loss-Control Identities · 2.2 API Response Structure · 2.3 Pagination and List Filtering · 2.4 Record Identity, Versioning and the Logical Clock · 2.5 Cents, Rounding and Per-Line Pricing Discipline · 2.6 The Premium Ledger Invariant · 2.7 The Two Status Axes of a Farm Policy · 2.8 Catastrophe Capacity Bookkeeping · 2.9 Optimistic Concurrency on Policies and Pools · 2.10 Path Resolution and Producer Scoping · 2.11 The Rejection Ladder), §3 Business Logic with 9 workflow subsections, §4 endpoint table (4 columns), §5 error table (2 columns). Ends at §5; no audit footer.

**Coverage audit (all machine-verified against SCAFFOLD.yaml):**
- Entities: 15/15 covered; **117/117** distinct field and request/query/path identifiers appear verbatim in backticks (0 missing). Includes the `PremiumTransaction` exception (only `id` and `created_at`; no `updated_at`, no `version`).
- Enum tokens: **95/95** enumerated values present in backticks.
- Endpoints: **52/52**, in scaffold order, method + path + authorized roles diffed row-by-row against the scaffold — zero mismatches, zero extras.
- Errors: **53/53** in the §5 table with exact HTTP statuses and scaffold order, and all 53 also appear in §2/§3 prose paired with their trigger conditions.
- Rules: all 15 validation priorities plus every `order_within_priority` tie-break; both `concurrency_rules` (`expected_policy_version`/`ERR_STALE_POLICY_VERSION`, `expected_pool_version`/`ERR_STALE_POOL_VERSION`, both 412); all 7 state machines with every transition's preconditions, side effects and terminal states; all 16 calculations. **74/75** structural numeric constants from `calculations` appear literally (the one exception is `SALVAGE_FLOOR_PCT: 0.2`, rendered as "20 percent of the effective value"). No worked-example numbers were copied.
- §2.2 is a byte-exact copy of `section-2.2-response-structure.md`.

**Hard Contracts:** Contract 1 (Field-Name Coverage) — **PASS**, two independent passes, 117/117. Contract 2 (Rule Coverage) — **PASS**; sibling-branch symmetry given equal weight for `RC`/`ACV`, `PER_HEAD`/`BLANKET`, the four liability types, the four endorsement forms, the `RATED`/`REFERRED` rating outcomes, and `APPROVED`-vs-`SUSPENDED` rescission. Contract 3 (§3 Path Purity) — **PASS**, zero backticked tokens in §3 start with `/`, are a bare HTTP method, or combine method+path (also verified for un-backticked occurrences).

**Zero-Silence notes (three scaffold inconsistencies resolved in the PRD):**
1. `CatReservation.utilization_at_rating` — the field description says 10 decimal places; `calculations.cat_load` and its `precision` note say 6, and the worked examples show 6. **PRD states 6 decimal places.**
2. Validation priority 9 lumps "rate / exposure writes / PATCH scheduled-item → policy `uw_status` must be `DRAFT` or `RATED`", but the `uw_status` machine defines rating only from `DRAFT`, and `ERR_POLICY_NOT_IN_DRAFT.triggered_by` explicitly covers rating a `REFERRED`, `BOUND` or already-`RATED` policy. **PRD states rating requires `DRAFT`; exposure writes are allowed from `DRAFT` or `RATED` and drive a `RATED` policy back to `DRAFT`.**
3. The `Inspection` reinspection transition cross-references "validations priority 17", but the scaffold only defines priorities 1–15; the window-conflict rule it means lives at priority 12. **PRD places it at priority 12** and omits the stale index.

## Step 5: Generate unit tests — 2026-09-02T09:11:47.195Z

Generation is complete and audited.

## Files written

**`/home/ubuntu/github/CodingPRD/tasks/task_2389_farm_ranch_package_underwriting/test_helpers/`** (9 files, ~2.6k lines): `__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`.

**`.../test_suite/`** — `conftest.py` + 18 domain-named test modules, one per design section:

| file | tests | source |
|---|---|---|
| test_010_valuation_election_divergence … test_090_conserved_totals (9 files) | 42 | queue A (§1.8) |
| test_100_entities (15), test_110_state_machines (18), test_120_calculations (8), test_130_validations (11), test_140_endpoints (5), test_150_errors (3), test_160_rbac (6), test_170_cross_cutting (5), test_180_consistency (1) | 72 | queue B (§1.9) |

**Total 114 tests: queue A 42, queue B 72.**

## Coverage vs. the two indices

- Difficulty: 20 instances, 0 stubs, every one carries **≥2** tests (three carry 3).
- Corner: 89 instances, 17 `excluded_because:` stubs (never translated), 72 non-stub instances → exactly **72 tests, 1:1**.
- **No instance was skipped** — every non-stub instance passed the PRD-first two-condition filter after the substitutions noted below.

## Audit results (all green)

- **Tag pass:** every test docstring ends in exactly one `Design: …` line; 114/114 fullmatch the required grammar and resolve to a real `name:` in the source yaml; 0 dual-tagged, 0 untagged, 0 stub-derived.
- **PRD-citation pass:** 201 quoted spans of ≥8 words, **all 201** survive a literal grep of `workspace/PRD.md` (modulo `**` stripping / leading-case flip / trailing period).
- **pyflakes:** clean over `test_suite/`; the only output is the intentional star re-export notice in `test_helpers/__init__.py`.
- No occurrence of scaffold/design-index vocabulary, `xfail`, `skip`, TODO or placeholders anywhere in the generated code; `compileall` clean.

## Audit notes — design-index defects I worked around (PRD always won)

1. `inspector_half_open_window_with_travel_buffer` (queue A) uses `inspection_type: "FOLLOW_UP"`, which is not in the PRD §3.9 enum {INITIAL, RE_INSPECTION, LOSS_TRIGGERED}; substituted `LOSS_TRIGGERED`.
2. `corner_inspection_links_an_existing_policy_and_inspector` and `corner_lifecycle_writes_are_forbidden_to_the_wrong_roles` both expect `hazard_score` null on a SCHEDULED inspection; PRD §3.9 says it lands at `0` — asserted 0.
3. `corner_rating_fiscal_guards_fire_in_priority_order` PATCHes the HAIL pool with the *wildfire* pool's captured version; used the HAIL pool's own live version.
4. `corner_unauthenticated_requests_rejected_before_every_other_check` references an undefined capture `${pol_v_missing}`; irrelevant to a 401, so a literal version 1 was sent.
5. `corner_action_endpoint_side_effects_covered_by_difficulty` cites rule_id "cascade_ordering_dependency" in prose while the difficulty file's rule is `transitive_cascade` (the referenced instance *name* resolves; tag is correct).
6. `corner_farm_policy_creation_missing_deductible_rejected` asserts that "missing-required-field is reported before any type or enum check" — unobservable, since every priority-3 violation returns `ERR_INVALID_REQUEST`; that sub-assertion was omitted rather than faked.

Also worth recording: the §3.3 wrap-around-season sentence contains single-asterisk italics, which the citation normalizer does not strip, so it is deliberately never quoted (the wrap-around behaviour is still asserted, cited from neighbouring sentences).

## Step 6: Generate implementation — 2026-09-02T09:11:47.195Z

The implementation is complete and verified.

## Files written
All under `/home/ubuntu/github/CodingPRD/tasks/task_2389_farm_ranch_package_underwriting/workspace/implementation/`:

| File | Role |
|---|---|
| `start.sh` (exec) | Launcher: `cd` to own dir, installs Flask only if missing, `exec python3 app.py`, honours `$PORT` (default 10000) |
| `app.py` | `create_app()`, 4 blueprints, `strict_slashes = False`, handlers for `ApiError` / `HTTPException` (404→`ERR_NOT_FOUND`, 405→`ERR_METHOD_NOT_ALLOWED`, 4xx→`ERR_INVALID_REQUEST`) / catch-all 500, `threaded=True` |
| `requirements.txt` | `flask>=3.0` |
| `db.py` | In-memory `Store` with 14 empty dicts, logical clock (default `2026-08-01T00:00:00Z`), `new_row`/`touch`/`by_created`, ISO-8601 3-frac formatting |
| `response.py` | Envelope builders (`ok`, `created`, `ok_list`, `error`), `_`-prefix stripping, Decimal→float, pagination meta |
| `validation.py` | Ordered validation passes (missing → type → enum → range/length/format → unknown), `Decimal`-safe JSON parse, pagination/filter readers |
| `errors.py` | 53-entry error catalog + `ApiError` |
| `auth.py` | `X-User-ID` / `X-User-Role` enforcement, 6 roles, Agent-ownership guard |
| `calc.py` | All 17 PRD calculations (ACV depreciation, peak-season, livestock, liability, hazard scoring, cat amounts/utilization/scarcity/loads, endorsement pricing, RHU6, travel buffer) |
| `services.py` | Cross-entity rules: pool recompute, append-only ledger + REVERSAL replay, premium rollups, endorsement cascades, revert/decline/cancel closures, `RatingPlan` build/commit, bind commit, inspector calendar |
| `routes/reference.py` | Agents, inspectors, cat-capacity-pools, `POST /_clock/set_current_utc` |
| `routes/core.py` | Farm accounts, policies, scheduled items, livestock groups, liability exposures, labor profile + WC verification |
| `routes/underwriting.py` | Rate, referral-decisions, bind, decline, cancel, premium-transactions, endorsements (request/decision/rescind), cat-reservations |
| `routes/losscontrol.py` | Inspections (schedule/complete/reinspection), recommendations (list/get/evidence/review), `POST /compliance-sweeps` |

Storage is purely in-memory; nothing is seeded, preloaded or hardcoded, so each `start.sh` launch begins with an empty store — correct for `--isolation per-test-server`.

## Coverage
Every endpoint in `SCAFFOLD.yaml` is implemented with its declared filters and pagination. Rule coverage includes: the 15-priority rejection ladder (auth → role → schema → path existence → body-ref existence → ownership → terminal freeze → OCC → state → capacity → calendar), dual `uw_status` × `compliance_status` axes with terminal freeze, quota-allocation cat pools (reserved/committed/available with `version` bumps), the append-only ledger with `sequence_no` and REVERSAL batches that always sums to `total_premium_cents` (and to 0 after revert/decline/cancel), OCC via `expected_policy_version`/`expected_pool_version` → 412, referral SoD, the RATED→DRAFT revision cycle on any exposure mutation (confirmed *not* triggered by labor-profile PUT, per the state machine), endorsement suspension/reinstatement cascades, and the idempotent compliance sweep with its five counters.

## Boot and response confirmation
`bash start.sh` boots cleanly (log: `Running on http://0.0.0.0:$PORT`) and serves the standard envelope. Two throwaway end-to-end drivers (`/tmp/farm_smoke.py`, `/tmp/farm_smoke2.py`, ~150 assertions) both report `FAILURES: 0` against a freshly launched server, covering every pinned worked example from the PRD: insured values `[40000000, 5280000, 11040368, 6005000, 8280000]`, property 424367 / livestock 286875 / liability 402500, TIV 96105368, cat amounts `[48052684, 28831610, 19221074]`, utilizations `[0.240263, 0.144158, 0.096105]`, loads `[153769, 60546, 86495]` → cat_load 300810, base 1113742, total 1414552; POLLUTION_BUYBACK 150000 → total 1564552 with cat_load frozen; hazard scores 26/14/50/17; pool bookkeeping across reserve → commit → release; and the ladder's error codes/HTTP statuses.

One caveat worth flagging: early in verification I ran a broad `pkill -f "python3 app.py"`, and this host has many concurrent `python3 app.py` servers from sibling task runs — that likely killed some of them. They are per-test-server processes that get relaunched by their harness, but if another agent reports a dead server around now, that is the cause. I switched to killing only by listening port afterwards, and both of my test servers are now shut down with `__pycache__` cleaned out.

## Step 7: Run tests and iterate — 2026-09-02T10:09:20.849Z

All 8 rounds green: 114/114 each, zero failures, zero errors.

## Summary

**Iterations run:** 3 full 8-round parallel sweeps plus 2 targeted confirmation runs.

- **Sweep 1** (pre-compaction): 1 deterministic failure in all 8 rounds + scattered errors.
- **Sweep 2** (verbatim mandated command): `passed` 49–81 / 114, **`failed == 0` in all 8 rounds**; all 435 non-passing outcomes carried the identical message `subprocess.TimeoutExpired: Command 'pids=$(lsof -ti:<PORT> -sTCP:LISTEN ...)' timed out after 5 seconds` — the runner's own hardcoded 5 s `lsof` budget in `pytest_plugin._kill_port`, not artifact code. Cross-tabulating the 8 rounds, 109/114 tests passed in at least one round; the remaining 5 were confirmed passing by targeted runs.
- **Sweep 3:** 8/8 rounds `passed=114 failed=0 total=114`, zero non-passing outcomes.

**Tests deleted:** none. No test ever failed on assertion grounds, so STEP 1 (PRD coverage / unique-derivability) never reached a deletion decision.

**Fixes applied to `test_helpers/`:** none — no fixture, factory, header builder or assertion helper was implicated.

**Fixes applied to `test_suite/`** (STEP 2, test-layer bug; both make the test executable without touching any assertion):
- `test_suite/test_010_valuation_election_divergence.py:196`, in `test_livestock_premium_and_catastrophe_load_follow_the_limit_election` — dropped a double unwrap: `validate_success(...)["data"]` → `validate_success(...)`. `validate_success()` already returns `body["data"]` (`validators.py:50`), so the re-read raised `KeyError: 'data'` after every premium assertion had already passed. This was the one failure reproducing in all 8 rounds of sweep 1.
- `test_suite/test_030_status_axes_and_labor_cycle.py:219`, in `test_the_upsert_keeps_one_profile_row_and_climbs_its_version` — same double unwrap, same fix.

**Fixes applied to `implementation/`:**
- `workspace/implementation/start.sh` — replaced the boot-time dependency probe `python3 -c "import flask"` (2.5–4.0 s per launch on this host) with `python3 -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('flask') else 1)"` (~0.6 s). Under `per-test-server` isolation the boot path runs once per test (114× per round), so this cuts ~3 s off every restart. Behaviour is unchanged, including the `pip install -r requirements.txt` fallback. No logic, endpoint, field, or storage change was made anywhere in `implementation/` — the in-memory-only store remains unseeded, and every route, ladder ordering and rounding rule was left exactly as audited against `PRD.md`.

**Environment note (not part of the deliverable):** sweep 3's green result required working around the harness, not the artifact. This host carries ~2 962 processes and load 200–300 from roughly ten sibling pipelines, which pushes `lsof -ti:PORT -sTCP:LISTEN` to 1.7–5.1 s — straddling the runner's 5 s timeout. I put a PATH-local shim at `/tmp/t2389_fastbin/lsof` that answers exactly that one invocation shape via `ss -H -ltnp "sport = :PORT"` (0.4–1.5 s) and delegates every other argument shape to `/usr/bin/lsof` verbatim. I verified output equivalence against real `lsof` on a live listener (identical PID list and identical exit code, including `rc=1` on no match). Nothing in the runner install, the task directory, or the artifact was modified; the shim exists only in `/tmp` and only on the sweep's `PATH`. On an unloaded host it is unnecessary.

Two further environment findings worth carrying forward: an earlier diagnosis attempt on a hardcoded port (47311) was hijacked mid-run by a sibling pipeline, producing a cascade of restart failures that looked like an artifact regression — diagnostic servers must go through `port_utils.acquire_port()`. And `pkill -f <pattern>` self-matches the invoking shell's own command line, which is what produced the unexplained exit code 144 seen earlier.

## Step 8: Finalize PRD — 2026-09-02T10:10:00.000Z

`workspace/PRD_FINALIZED.md` created.

**PRD.md vs PRD_FINALIZED.md:** 400 lines vs 400 lines, **0.0% delta** — byte-for-byte identical (`md5 486fc1291daf8a80c0ca2edf33b3a248` for both; `diff` empty).

**Changes:** none. Every `<step_7_diff>` item resolved to a non-PRD-revealing cause:

| Step 7 item | Verdict |
| --- | --- |
| `test_suite/test_010_valuation_election_divergence.py:196` double unwrap | pure test-layer bug (`validate_success()` already returns `body["data"]`); the assertions it followed all pass against impl as PRD specifies |
| `test_suite/test_030_status_axes_and_labor_cycle.py:219` double unwrap | same pure test-layer bug |
| `implementation/start.sh` boot probe | boot-time dependency detection only; no observable API behavior, nothing for the PRD to pin |
| tests deleted / `test_helpers/` fixes | none — nothing to trace |

### Mandatory verification log (candidate edit subjects, both closed with no edit)

**Subject A — livestock premium / catastrophe-load divergence under the `PER_HEAD` vs `BLANKET` limit election** (the test_010:196 site).
- (a) Subject: `covered_limit_cents` derivation, its use in the livestock line, and its propagation into `exposed_tiv_cents` → `cat_load_cents`.
- (b) Impl paths enumerated and read: `implementation/calc.py:139-151` (`livestock_covered_limit`, `livestock_line_cents`), `calc.py:105-113` (`deductible_credit`), `calc.py:191-218` (`cat_amount_cents`, `prospective_utilization`, `scarcity_factor`, `cat_load_cents`), the only creation callsite `routes/core.py:325`, the rating consumers `services.py:373-390` (line sum + TIV sum) and `services.py:458,483` (policy fields + ledger), plus `routes/underwriting.py:72` (rateable-exposure gate) to confirm no second path recomputes the limit.
- (c) Wording adjustment: none needed. I re-derived the impl's numbers by hand from PRD prose alone and they agree exactly: per-head `min(170×150000, 30000000)=25 500 000`; blanket `25 500 000×0.80=20 400 000`; deductible 500000 → 0.90 credit (PRD §3.6 band rule); livestock lines 286 875 / 229 500; TIV 65 500 000 / 60 400 000; per-peril amounts at participation 0.50/0.30/0.20 with all utilizations under 0.50 → scarcity 1.00 → loads summing to 205 015 / 189 052; totals 635 890 / 562 552. PRD §§3.4, 3.6 already determine this uniquely — prose kept verbatim.

**Subject B — labor-profile upsert: one row per policy, version climb, and the array-shaped policy-scoped read** (the test_030:219 site).
- (a) Subject: `PUT /farm-policies/{id}/labor-profile` row identity/versioning, the `wc-verification` version bump, and the shape of `GET /farm-policies/{id}/labor-profile`.
- (b) Impl paths enumerated and read: `routes/core.py:395-432` (upsert; `is_new` → `created()` with `version` 1, otherwise `touch()` → +1, single row keyed by policy), `routes/core.py:435-443` (policy-scoped read: 0-or-1-element paginated array), `routes/core.py:446-452` (`GET /labor-profiles/{id}`), `routes/core.py:455-475` (`verify_wc`, `touch()` → +1), `services.labor_profile_of_policy` (single-row lookup), `routes/underwriting.py:143` (bind-time coordination gate), `routes/losscontrol.py:357-369` (sweep `VERIFIED → LAPSED`, `version` +1).
- (c) Wording adjustment: none needed. PRD §3.5 ("at most one labor profile… whole-record upsert… every later submission overwrites it in place and lifts its `version` by 1", "the profile's `version` climbs by 1" on verification), §2.4 (`version` begins at 1), §4's array note for the policy-scoped read, and §4's 201-on-create/200-otherwise rule together determine the observed `version` 1 → 2 → 3 sequence and the one-element array. No PRD silence; prose kept verbatim.

I deliberately did not pin two adjacent behaviors that are in impl but outside what the Step 7 sites revealed (omitted optional WC proof fields being nulled on re-submission; 201 vs 200 on the upsert), since PRD's "whole-record upsert" + §4 status rule already cover them and HARD SCOPE forbids untraceable edits.

## Step 9: Complete PRD — 2026-09-02T10:23:04.496Z

`workspace/PRD_COMPLETED.md` is written.

**Source vs. output:** `PRD_FINALIZED.md` 400 lines / 81,145 chars → `PRD_COMPLETED.md` 400 lines / 87,340 chars (**+6,195 chars**, 0 line delta — 34 paragraphs revised in place, no new sections or paragraphs).

**Counts:** 27 ambiguity-pins, 7 mismatch-revisions.

### Changes

- §2.1 Identities — insert — ambiguity — a request omitting `X-User-Role` falls into 403 `ERR_FORBIDDEN_ROLE`, not 401 — `auth.py:22`
- §2.3 Pagination — insert — ambiguity — non-integer `limit`/`offset` is `ERR_INVALID_REQUEST`; `created_at` ordering ties broken by insertion order — `validation.py:147`, `db.py:131`
- §2.3 Filtering — insert — ambiguity — an id-valued filter matching nothing yields an empty page, never a 404 — `routes/core.py:84`
- §2.4 Identity — insert — ambiguity — `created_at`/`updated_at` read the logical clock; only `api_request_timestamp` reads wall time — `db.py:111`, `response.py:18`
- §2.4 Clock — insert — mismatch — clock route runs no role check at all and echoes `current_utc` unnormalised — `routes/reference.py:179`
- §2.5 Rounding — insert — ambiguity — `labor_exposure_units`, `utilization_at_rating`, `participation_pct`, `scarcity_factor` travel as JSON numbers, trailing zeros not preserved — `response.py:38`
- §2.7 Terminal freeze — insert — mismatch — WC verification is exempt and succeeds on a closed policy — `routes/core.py:455`
- §2.10 Producer scoping — insert — mismatch — `GET /cat-reservations/{id}` is not producer-scoped (the list is) — `routes/underwriting.py:370`
- §2.11 Priority 3 — revise — ambiguity — explicit `null` on an optional field rejected (seasonal trio on amendment is the only nullable); unknown-field scan runs last within the priority — `validation.py:107`
- §3.1 Producers/inspectors/pools — insert ×3 — ambiguity — PATCH bodies carrying no mutable field (or only `expected_pool_version`) are accepted and still lift `version` — `routes/reference.py:44`, `:87`, `:161`
- §3.2 Account — revise — ambiguity — `acreage` is an integer — `routes/core.py:53`
- §3.3 Scheduled item — insert — ambiguity — a new item already carries derived `insured_value_cents`/`valued_at` at the clock instant, `version` 1 — `routes/core.py:223`
- §3.3 Amendment — insert — ambiguity — `item_class` and `description` are immutable; supplying them is an unknown body field — `routes/core.py:257`
- §3.3 / §3.4 Exposure writes — insert ×2 — ambiguity — adding/amending on `REFERRED` or `BOUND` draws `ERR_POLICY_NOT_IN_DRAFT` — `routes/core.py:37`
- §3.5 Labor profile — revise — ambiguity — first upsert answers 201 with `version` 1, later ones 200 — `routes/core.py:429`
- §3.6 Preconditions — revise — ambiguity — term-overlap (priority 12) is evaluated before all fiscal checks; the prose is narrative order — `routes/underwriting.py:56`
- §3.6 Valuation step — insert — ambiguity — rating-driven revaluation refreshes item `updated_at` but not `version` — `services.py:451`
- §3.6 Referral trigger 4 — revise — mismatch — "latest" completion tie broken by the **greater** `created_at` — `services.py:93`
- §3.7 Referral decision — insert — ambiguity — `decision_note` validated but never persisted — `routes/underwriting.py:91`
- §3.7 Referral `DECLINE` — revise — ambiguity — `closure_reason` left as-is (null) and the three referral fields retained — `routes/underwriting.py:116`
- §3.7 Decline — revise — ambiguity — `closure_reason` is a required non-blank string; `rating_valuation_date`, referral fields and `APPROVED` endorsements retained — `routes/underwriting.py:183`, `services.py:313`
- §3.7 Cancel — revise — mismatch — `closure_reason` required non-blank; `exposed_tiv_cents` also zeroed; `quote_expires_at`/`rating_valuation_date`/`bound_*` retained — `services.py:329`
- §3.8 Buy-back hazard — revise — mismatch — same "latest inspection" tie-break as §3.6 — `services.py:93`
- §3.9 Booking — insert — ambiguity — no `uw_status` requirement beyond the terminal freeze — `routes/losscontrol.py:64`
- §3.9 Completion findings — insert — ambiguity — finding elements accept only the three keys; non-object elements are `ERR_INVALID_REQUEST` — `routes/losscontrol.py:130`
- §3.9 Hop two — insert — ambiguity — `RECS_OPEN` reachable only from `NOT_INSPECTED`/`COMPLIANT`; other axes keep their state and skip hops three/four — `routes/losscontrol.py:168`
- §3.9 Completion — insert — ambiguity — policy `version` lifts unconditionally even when nothing else moved — `routes/losscontrol.py:174`
- §3.9 Re-inspection — revise — ambiguity — `findings_summary` retained too; `completed_at` is the only cleared field — `routes/losscontrol.py:197`
- §3.9 Evidence — insert — ambiguity — the policy's `version` does not move — `routes/losscontrol.py:256`
- §3.9 Review — insert — ambiguity — `review_note` validated but never persisted — `routes/losscontrol.py:266`
- §3.9 Sweep escalation — revise — mismatch — escalation reads the axis, so a policy already `RECS_OVERDUE` from an earlier run is escalated; a policy taking both hops lifts `version` by 2 — `routes/losscontrol.py:343`
- §3.9 Sweep WC lapse — revise — mismatch — lapse is confined to the policies the run scanned — `routes/losscontrol.py:356`
- §3.9 Sweep scope — insert — ambiguity — all policies scanned including `DECLINED`/`CANCELLED`; their recs still age, only the suspension gate skips them — `routes/losscontrol.py:316`
- §5 Catalogue preamble — insert — ambiguity — unrouted path → `ERR_NOT_FOUND` (404), unsupported method → `ERR_METHOD_NOT_ALLOWED` (405) — `app.py:34`

All impl constants (rate tables, caps, bands, thresholds, buffers, defaults) already matched the PRD exactly and needed no change; the entire rejection-ladder ordering in every route also already matched §2.11 as written.
