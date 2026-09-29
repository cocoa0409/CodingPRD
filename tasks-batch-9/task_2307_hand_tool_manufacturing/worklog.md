# Worklog — task_2307_hand_tool_manufacturing

## Step 1: Create Task Directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2307_hand_tool_manufacturing/` and `tasks/task_2307_hand_tool_manufacturing/workspace/` (directory name pre-allocated by the caller; no index scan performed).

## Step 2: Generate Scaffold — 2026-09-01T16:14:00.000Z

All three scaffold artifacts are complete and lint-clean.

## Output files
- `/home/ubuntu/github/CodingPRD/tasks/task_2307_hand_tool_manufacturing/SCAFFOLD.yaml` (§1.0–§1.7, 145 KB) — top-level keys only `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` (no design keys); scenario text verified verbatim.
- `/home/ubuntu/github/CodingPRD/tasks/task_2307_hand_tool_manufacturing/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (99 KB) — single key `scaffold_difficulty_design`.
- `/home/ubuntu/github/CodingPRD/tasks/task_2307_hand_tool_manufacturing/SCAFFOLD_CORNER_DESIGN.yaml` (250 KB) — single key `scaffold_corner_design`.

## Inventory
- **Entities:** 13 (`ToolSku` self-referential lineage, `ProductionLot`, `HeatTreatFurnace`, `SaltSprayChamber`, `FurnaceCampaign`, `TestRun`, `PackConfiguration`, `PackMember` junction, `WarrantyProgram`, `Claimant`, `WarrantyClaim`, `ClaimLine` immutable, `CounterfeitReport`); 14 FKs, graph topology.
- **State machines:** 10 declared blocks over 8 entities — `ProductionLot` carries three parallel dimensions (`process_status`, `cert_status` with a REJECTED→DRAFT rework cycle, `disposition`), plus `HeatTreatFurnace`, `FurnaceCampaign`, `TestRun`, `PackConfiguration`, `WarrantyClaim` (branching + FRAUD_HOLD→SUBMITTED cycle), `Claimant`, `CounterfeitReport`.
- **Calculations:** 13 (incl. two dual-variant: `lot_hardness_index` SAMPLE/POOLED, `claimant_fraud_score` INTAKE/ADJUDICATION; `proof_torque_requirement` combinatorial; `claim_reserve_charge` per-line-then-sum; `brand_risk_rollup` weighted scoring; `pack_pricing` with a tier keyed on the pre-surcharge subtotal).
- **Validations:** 63 rules on a single explicit priority ladder (100 → 930). **Endpoints:** 64 under `/toolworks`. **Errors:** 66. **Roles:** 7 with `segregation_of_duties` (X-User-ID on `WarrantyClaim.held_by_user_id`). **OCC rules:** 2 (stale parent SKU version on lot release, stale programme version on claim approval; both 412).
- **Difficulty design:** 9/9 rules × exactly 2 instances = 18, target band `expert_plus`.
- **Corner design:** 9/9 guide sections, **83 instances** (62 full recipes + 21 `excluded_because` stubs) — entities 12, state_machines 15, calculations 12, validations 22, endpoints 6, errors 3, rbac 4, cross_cutting_complexity_layers 8, consistency_model 1.

## Coverage audit (all green)
- 66/66 error codes triggered across §1.8+§1.9; zero references to undeclared codes.
- 64/64 endpoints exercised; zero calls to undeclared paths.
- All 13 entities and all 13 calculations referenced in §1.9; all 63 validation priorities cited.
- 101 instance names unique across both design files; all 21 stubs cite an existing §1.8 instance by exact name and carry no `test_recipe`.
- Zero forbidden concurrency vocabulary; the logical-clock endpoint (`output: None`) is never given `captures`, and its description pins the default `2026-08-01T00:00:00Z`.

## Lint verdict (verbatim)
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2307_hand_tool_manufacturing/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2307_hand_tool_manufacturing/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2307_hand_tool_manufacturing/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    64
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     62
  Calls scanned (§1.8+§1.9):  856

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Fixes applied during the lint loop: a capture of a non-existent `SaltSprayChamber.scheduled_coupon_load` (reworked to assert the coupon load is derived on demand, never denormalised), seven `$.data.total_count` captures on list endpoints (moved into asserts / element-form captures), and a PyYAML flow-mapping break on unquoted `$.data[0].x`. Two consistency repairs also landed: validation priority 213 was added to the body-FK instance's grounds, and the one occurrence of banned wording ("simultaneously") was reworded. No sibling task directory was read at any point.

## Step 3: Copy Shared Files — 2026-09-01T16:15:00.000Z

Copied `INSTRUCTION.md` from project root to `tasks/task_2307_hand_tool_manufacturing/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T16:30:00.000Z

PRD generated and audited.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2307_hand_tool_manufacturing/workspace/PRD.md` — **412 lines**

**Section inventory**
- `# 1. Introduction` — 3 paragraphs, domain hook (torque promise / warranty liability / counterfeit leakage), no "This document outlines".
- `## 2. Global Specifications & System-Wide Principles` — 10 subsections: 2.1 Users, Roles and the Segregation of Duties · 2.2 API Response Structure (pasted verbatim, diff-verified against `skills/prd-bench-doc-generator/section-2.2-response-structure.md`) · 2.3 Pagination, Ordering and List Filters · 2.4 Resource Identity, Revision Counters and Nested Paths · 2.5 Measurement Precision and Rounding Discipline · 2.6 Stale-Read Protection on Shared Parents · 2.7 The Order in Which a Request Is Refused · 2.8 The Logical Shop Clock · 2.9 Conserved Quantities: Specimens, Units and Reserve Money · 2.10 Cascade Discipline.
- `## 3. Business Logic & Workflows` — 9 subsections (catalogue/lineage; lots + furnace campaigns; test scheduling vs specimen pool; readings adjudication + rejection cascade; certification/rework/release; retail packaging; warranty intake; claim adjudication; counterfeit cascade).
- `## 4. Endpoint Definitions` — 64 rows, exactly 4 columns (pipe-count verified on every row).
- `## 5. Error Code Catalogue` — 66 rows, exactly 2 columns. Document ends here; no audit footer.

**Coverage audit (all mechanical, re-run after final edits)**
- Contract 1 field-name coverage: **99/99** entity field names, **70/70** request-body/query/path identifiers, all present verbatim in backticks. **PASS**
- Enum literals: **62/62** in backticks. State-machine states: **32/32**. All **34** transitions (incl. the 5 system/cascade transitions) narrated with side effects. Roles: **7/7**.
- Errors: **66/66** in the §5 table and every one also referenced in §2/§3 prose (`ERR_INVALID_REQUEST` was table-only on the first pass and was given a prose home in §2.7).
- Validations: **63/63** represented, including all `applies_to` scope enumerations (the 5-endpoint cert-state gate, the 5-endpoint quarantine gate, the 7-code uniqueness rule) and the pinned orderings (readings-length before run state; stale-version after target state but before business rules; alloy before window before charge; SoD last).
- Calculations: **13/13** with every constant in prose; worked-example numbers deliberately omitted, rule constants all present (channel reserve 62/45/78 percent, 4 percent surcharge, buffers, thresholds, clamps).
- Contract 2 high-risk categories: OCC framed purely as stale-version reads (no "simultaneously"/"race"/"first-writer-wins" anywhere — grep-verified); both cascades specified link-by-link with `created_at` ASC ordering; sibling branches given equal density (pass/fail, deny vs deny-fraud, APPROVED vs FULFILLED revocation, PLATED→MACHINED vs ASSEMBLED→MACHINED rework, confirm vs dismiss, intake vs adjudication fraud variants, sample vs pooled hardness). **PASS**
- Contract 3 §3 path purity: zero backticked tokens in §3 beginning with `/` or naming an HTTP method. **PASS**
- No pseudocode operators (`>=`, `+=`, `==`, `min(`…) and no fuzzy quantifiers in the body; only the two §2.2 JSON fences.

**Scaffold issues found (not resolvable without the withheld design files)**
1. **`REWORK_LIMIT` has no numeric value** anywhere in `SCAFFOLD.yaml` (9 references, no `constants` entry). The PRD states the limit as **2 completed rework cycles** so the rule is implementable — if the hidden tests assume a different number, this needs reconciling.
2. **Contradiction on what opens the certification dossier.** The `cert_status` state machine says `DRAFT → IN_TEST` fires on the first successful test-run scheduling; the `/production-lots/{id}/advance` endpoint `side_effects` line says it fires "on the first advance out of FORGED". I followed the state machine, since the dimension note explicitly allows a lot to be `ASSEMBLED` while still `DRAFT`.
3. Minor: the `/clear-hold` endpoint `side_effects` line says `held_by_user_id` is cleared to null, while the state-machine transition says it is RETAINED (and validation 902 depends on retention). The PRD follows the state machine.
4. Minor: pack approval certification gate — the state machine adds "and `disposition` `RELEASED`" while validation 473 and the error condition require only a lot with `cert_status` `CERTIFIED`. The PRD follows validation 473.

## Step 5: Generate Unit Tests — 2026-09-01T18:15:00.000Z

Generation is complete. Final state and audit results:

## Deliverables

**Stage 1 — `/home/ubuntu/github/CodingPRD/tasks/task_2307_hand_tool_manufacturing/test_helpers/`** (9 modules, 2 259 lines): `__init__.py` (barrel), `api_client.py` (one method per declared endpoint), `api_errors.py` (every `ApiErrorId` + `HTTP_STATUS_CODES` registered with the framework), `types.py`, `constants.py`, `factories.py`, `fixtures.py` (tiered composite setups), `assertions.py` (entity contracts + the three §2.9 ledger invariants), `test_users.py` (per-role header builders, entity-backed `Claimant` headers, `NO_ROLE_HEADERS`, `make_headers_with_role`). Plus `test_suite/conftest.py`.

**Stage 2 — `test_suite/`: 19 test files, 178 test functions, 211 collected cases** (parametrized families expand). Files 01–07 are queue A; 08–19 are queue B. The three added this session:
- `test_17_certification_and_brand_error_paths.py` — 8 tests, the 3 `errors` instances
- `test_18_role_identity_and_duty_separation.py` — 12 tests, the 4 `rbac` instances
- `test_19_stale_parents_and_derived_field_currency.py` — 12 tests, the 3 non-stub `cross_cutting_complexity_layers` instances + the 1 `consistency_model` instance

## Translation counts
- **Queue A (Difficulty):** 18/18 instances, 0 stubs, 54 tests — every instance has >=2 tests (min 2, max 5).
- **Queue B (Corner):** 62/62 non-stub instances, 124 tests — every instance has >=1 test.
- Programmatic audit: `MISSING: []`, `STUBS TAGGED: []`, `ORPHAN TAGS: []`, queue-A-under-2: none.

## Skipped
- **No non-stub instance was skipped.** The 21 `excluded_because:` stubs in the corner index were not translated (per contract).
- Assertion-level omissions where the PRD does not uniquely derive the corner's expectation: the `GET /claimants/{other}` -> `ERR_CLAIMANT_MISMATCH` assertion (§2.1 scopes ownership to filing, line-adding and claim-reading only); version tokens of `0` (§2.6 declares no numeric range, so `0` could legitimately be `ERR_INVALID_REQUEST` — replaced with equivalent below/above probes off a version-2 SKU and a genuinely stale post-round-trip programme token); non-declared fields `approved_at`/`released_at`; the corner's pagination default of 20 (PRD §2.3 says 10).

## Audits
- `py_compile` + `pyflakes` on `test_suite/*.py`: **clean**.
- **Citation pass:** 178 quotes checked against `workspace/PRD.md` after whitespace normalisation — **0 non-verbatim**; every test has exactly one `PRD §x.y: "…"` quote and exactly one trailing `Design:` line (no untagged, dual-tagged or dangling tags). Two pre-existing paraphrases were found and corrected to verbatim §2.9 and §2.4 sentences (in `test_11` and `test_15`).
- **Scaffold-citation pass:** 0 occurrences of "scaffold" anywhere in `test_suite/` or `test_helpers/`.
- Every file has >=5 tests (range 6–14).

## Step 6: Generate Implementation — 2026-09-01T17:50:00.000Z

Implementation complete and boot-verified.

## Files created — `/home/ubuntu/github/CodingPRD/tasks/task_2307_hand_tool_manufacturing/workspace/implementation/`

Core (2,826 lines total):
- `start.sh` — `exec python3 app.py`, `PORT` env (default 10000), pip install only when Flask is missing so per-test reboots are fast; `requirements.txt` (`Flask>=2.2`)
- `app.py` — blueprint registration, `ApiError`/`LineageError`/`HTTPException`/catch-all handlers emitting the error envelope, global `RLock` per request, `threaded=True`, `use_reloader=False`
- `store.py` — 13 in-memory dicts, logical clock pinned at `2026-08-01T00:00:00Z`, `base_row`/`with_common`/`touch`/`sorted_rows` (canonical `created_at` ASC + insertion tiebreak). No seeding: all 11 collections return `total_count: 0` on a fresh boot (verified)
- `envelope.py`, `errors.py`, `validate.py`, `calculations.py`, `serialize.py`, `services.py`
- `routes/` — `__init__.py`, `helpers.py`, `skus.py`, `shop.py`, `lots.py`, `testruns.py`, `packs.py`, `warranty.py`, `brand.py`, `clock.py`

## Coverage

- **Endpoints: 64 implemented — exact set match with SCAFFOLD.yaml** (diffed method+path programmatically: 0 missing, 0 extra).
- **Error codes: 66 wired, and every HTTP status matches the scaffold catalogue exactly** (diffed programmatically: 0 missing, 0 extra, 0 status mismatches). Refusals follow the single global ladder (auth 100/110 -> claimant ownership 120 -> path/body existence 200-216 -> shape 300-341 -> entity state 400-411 -> OCC 450/451 -> cross-entity 470-474 -> safety 500-521 -> temporal 600/601 -> capacity 700-710 -> fiscal 800/810 -> integrity 900-930).
- **State machines (11):** lot `cert_status`, lot `process_status` (single-step advance), lot `disposition`, furnace `status`, campaign `status` (incl. cascade `SCHEDULED -> RELEASED`), test-run `status`, pack `status`, claim `status` (7 states incl. `FRAUD_HOLD` cycle), claimant `status`, report `status`, SKU `warranty_posture` (derived).
- **Calculations (13):** `proof_torque_requirement` (recomputed on amendment, pinned per lot), `lot_hardness_index` dual-variant SAMPLE_MEAN/POOLED, `test_run_outcome` (per-test governing statistic + margin), `report_risk_points` frozen at filing, posture derivation, `claimant_fraud_score` dual-variant (INTAKE 365-day window / ADJUDICATION lifetime + 25-per-counterfeit-link), claim reserve charge (round-per-line-then-sum), pack pricing 3-step + security surcharge breaks, and the three conserved ledgers (specimens, replacement units, reserve money). All Decimal + ROUND_HALF_UP, money in integer cents.
- **Cascades:** mandatory FAIL -> lot `REJECTED`+`QUARANTINED`, campaigns released, open runs voided, specimens returned; counterfeit CONFIRMED -> 5-link posture cascade with `COUNTERFEIT_POSTURE` holds (`held_by_user_id` null), programme `open_hold_count`/`version` updates, claimant adjudication rescoring, plus APPROVED-pack withdrawal on `SUSPENDED`.

## Boot verification

Booted via `bash start.sh` four times on ports 10123-10126. Verified live: full forge->heat-treat->test->certify->release chain (`proof_torque_required_nm` 216.2 and 145.0, pooled hardness 47.0/49.0, specimen ledger 20->9 available/11 consumed), warranty intake->lines->approve->fulfill (reserve 900 cents, programme balance 999100), pack pricing (SECURITY 4000+350=4350; MULTIPACK 5000x3x0.88=13200), counterfeit confirm -> `RESTRICTED`(50) -> `SUSPENDED`(100) with auto-hold and adjudication score 34, and ~30 negative cases returning the correct codes/statuses (`ERR_FURNACE_WINDOW_CONFLICT`, `ERR_CHAMBER_CAPACITY_EXCEEDED`, `ERR_SOAK_TIME_TOO_SHORT`, `ERR_MANDATORY_TEST_MISSING`, `ERR_STALE_PROGRAM_VERSION` 412, `ERR_SKU_WARRANTY_RESTRICTED`, `ERR_RESERVE_INSUFFICIENT` 402, `ERR_SEGREGATION_OF_DUTIES`, `ERR_SKU_LINEAGE_CYCLE`, `ERR_LINEAGE_FAMILY_MISMATCH`, `ERR_DUPLICATE_CODE`, `ERR_DUPLICATE_OPEN_CLAIM`, `ERR_CLAIMANT_MISMATCH`, `ERR_INVALID_WINDOW`, `ERR_INVALID_PAGINATION`, ...). Clock endpoint accepts no-header and `PlatformAdmin`, rejects other roles with 403. No tracebacks in any server log; all servers stopped afterwards.

Note: the test directories, difficulty/corner design files and sibling task dirs were not read, per the contract.

## Step 7: Run Tests and Iterate — 2026-09-01T21:15:00.000Z

All eight rounds are green. Final sweep result:

```
round 1: total=205 passed=205 failed=0 errors=0   (1245s)
round 2: total=205 passed=205 failed=0 errors=0   (1356s)
round 3: total=205 passed=205 failed=0 errors=0   (1263s)
round 4: total=205 passed=205 failed=0 errors=0   (1299s)
round 5: total=205 passed=205 failed=0 errors=0   (1389s)
round 6: total=205 passed=205 failed=0 errors=0   (1283s)
round 7: total=205 passed=205 failed=0 errors=0   (1407s)
round 8: total=205 passed=205 failed=0 errors=0   (1277s)
failure union across all 8 rounds: 0
```

Results files: `workspace/implementation/results.1.json` … `results.8.json`

## Summary

**Iterations run:** 5 full 8-round parallel sweeps, plus one targeted single-module reproduction (`test_03_furnace_and_chamber_scheduling_depth.py`) used to read a setup traceback without waiting ~20 min for a round to finish.

**Tests deleted:** none. No test in `test_suite/` was found to assert a scaffold-only rule or a non-uniquely-derivable outcome; STEP 1a/1b was never reached, because every union entry across sweeps 1–4 resolved at STEP 0 to either a `test_helpers` defect or a runner/host artifact.

**Fixes applied to `test_helpers/`:**
- `test_helpers/factories.py` — factories `test_run_payload` / `test_results_payload` renamed to `make_test_run_payload` / `make_test_results_payload`. `test_helpers/__init__.py` does `from .factories import *`, so their `test_` prefix made pytest collect them as tests in every importing module; they errored with `fixture 'lot_id' not found` / `fixture 'readings' not found` in 6 modules x 8 rounds. Call sites updated in `test_helpers/fixtures.py` and in `test_suite/test_02_…`, `test_03_…`, `test_09_…`, `test_12_…`, `test_15_…`. Collection went 211 -> 205 items; the six phantom entries vanished. No assertion was weakened, no fixture semantics changed.

**Fixes applied to `implementation/`:** no PRD-governed business logic was touched — `calculations.py`, `services.py`, `validate.py`, `serialize.py`, `store.py`, `routes/` are unchanged from the state they were in when I took over. Only the process entry point moved:
- `workspace/implementation/serve.py` (new) — process entry; `app.py` is now purely the WSGI module (its `import os` and `if __name__ == "__main__"` block were removed). Split so the running process's command line is `python3 serve.py`, which sibling task pipelines' broad `pkill -f app.py` does not match.
- `serve.py` pins `WSGIRequestHandler.protocol_version = "HTTP/1.0"` and runs `app.run(threaded=True)`. The server therefore closes the TCP connection after every response, so a client `requests.Session()` can never hand a request to a socket the server already discarded — that was the cause of the 1-in-8 `ConnectionResetError(104)` / `IncompleteRead` on the two chamber-capacity tests. (An intermediate waitress-based entry point was tried and reverted: `port_utils.kill_port`'s own docstring notes the hazard it guards is "invisible for frameworks that close connections per-request", i.e. keep-alive is the aggravating case, and waitress also stretched SIGTERM teardown to 10.4 s.)
- `start.sh` now checks only `import flask` and `exec python3 serve.py`; `requirements.txt` reduced to `Flask>=2.2`.
- Audit confirms the cardinal storage rule holds: no `sqlite`, `pickle`, `shelve`, `json.dump`, `open(`, or `/tmp` anywhere in `implementation/*.py`; `store.py` is 13 in-memory dicts, no seeding.

**One infrastructure mitigation, not in the repo.** Sweeps 3 and 4 came back with 69- and 8-name unions in which *every* entry was `failed on setup with subprocess.TimeoutExpired: Command 'pids=$(lsof -ti:<port> -sTCP:LISTEN …'`, plus an `INTERNALERROR> Failed: Timeout (>30.0s)` that aborted the remainder of each round. `pytest_plugin._kill_port` runs that `lsof` once per test (205x/round) under a 5 s `subprocess.run(timeout=5)` that is not caught. On this host — 3000–5000 processes, `/proc/net/tcp{,6}` ~20 k lines, load average 250–3300 from a dozen concurrent sibling task pipelines — real `lsof` measured a 4.0 s median and a 6.8–10.7 s max, so it blew the 5 s budget routinely. Those entries are runner artifacts, not assertion failures, and were excluded from adjudication.

Neutralised with a task-private, argument-compatible `lsof` stand-in at `/tmp/tw2307/bin/lsof`, prepended to `PATH` only for the sweep: it finds the listener among the handful of nearby ancestor/descendant pids (matching `serve.py` cmdline + `PORT=<port>` in `/proc/<pid>/environ`), falls back to resolving the LISTEN socket inode from `/proc/net/tcp{,6}`, and delegates to `/usr/bin/lsof` for any other argument shape or when the port is held by something not ours. Verified pid-for-pid identical to real `lsof`, and 0.10 s median / 0.21 s max versus 1.0 s / 3.1 s. Round wall time also dropped from ~31 min to ~21 min. **Consequence: if the prescribed sweep is re-run on this host without that shim on `PATH` while load is high, expect the same `lsof` `TimeoutExpired` setup errors to reappear — they are not regressions in the suite or the implementation.** Copies of the driver and the run logs are at `/tmp/tw2307/sweep2307.sh` and `/tmp/tw2307/sweep_run_2307_final/`; the harness-only files were removed from `workspace/implementation/` so it now contains only the service plus the eight results files.

## Step 8: Finalize PRD — 2026-09-01T21:22:00.000Z

Created `workspace/PRD_FINALIZED.md` as a byte-identical copy of `PRD.md`. **Zero PRD edits are warranted.**

## Line counts
- `PRD.md`: 412 lines
- `PRD_FINALIZED.md`: 412 lines
- Delta: 0 lines, **0.00%**; `md5sum` identical (`73e7df62e7d8bc992929b5dcbbc380fa`).

## Per-item disposition of `<step_7_diff>`

Every union entry across all 5 sweeps resolved at STEP 0 to a `test_helpers` defect or a runner/host artifact — STEP 1a/1b was never reached, no test was deleted, and no assertion was weakened. There is therefore no site where Step 7 revealed PRD-silence or PRD-mismatch, and consequently nothing to pin.

- **`test_helpers/factories.py` rename (`test_run_payload` -> `make_test_run_payload`, `test_results_payload` -> `make_test_results_payload`), plus call-site updates in `fixtures.py` and 5 test modules** — NO PRD EDIT. This is a pytest *collection* collision: the `test_` prefix plus `from .factories import *` in `test_helpers/__init__.py` made pytest treat the factories as test functions and demand `lot_id` / `readings` as fixtures. Collection count 211 -> 205 is purely the six phantom entries disappearing. The payloads the factories build are unchanged, so no request shape, default, or derived value the PRD governs is affected.
- **`serve.py` added as process entry; `app.py` reduced to the pure WSGI module (`import os` and the `__main__` block removed)** — NO PRD EDIT. Pure process plumbing so the command line is `python3 serve.py` rather than `app.py` (sibling pipelines' broad `pkill -f app.py`). `app.py` still constructs the Flask app, registers `routes.register(app)`, holds the `LOCK` before/teardown-request pair, and installs the same `ApiError` / `LineageError` / `HTTPException` / catch-all handlers. `serve.py` imports that same `app` object. No route, envelope, error-code, or status-code behavior moved or changed.
- **`WSGIRequestHandler.protocol_version = "HTTP/1.0"` and `app.run(threaded=True)`** — NO PRD EDIT. TCP connection lifetime only: the server closes after each response so a pooled `requests.Session()` cannot reuse a discarded socket (the cause of the 1-in-8 `ConnectionResetError(104)` / `IncompleteRead` on the two chamber-capacity tests). HTTP/1.0 is also Werkzeug's own default, so a fresh implementer using the Flask dev server reproduces this without being told. The PRD specifies no transport, keep-alive, or threading contract, and no response body, header, or status differs.
- **`start.sh` reduced to an `import flask` probe plus `exec python3 serve.py`; `requirements.txt` reduced to `Flask>=2.2`** — NO PRD EDIT. Boot/dependency plumbing with no request-visible surface.
- **`/tmp/tw2307/bin/lsof` stand-in prepended to PATH** — NO PRD EDIT. Outside the repo entirely; works around `pytest_plugin._kill_port`'s 5 s `lsof` timeout under host load 250–3300. Harness artifact.
- **Storage audit (`store.py` = 13 in-memory dicts, no seeding, no sqlite/pickle/shelve/json.dump/`open(/tmp`)** — NO PRD EDIT. This was a *verification* that produced no change: `store.py`'s `reset()` creates 13 empty dicts and sets `clock = INITIAL_CLOCK = 2026-08-01T00:00:00Z`, which is exactly what §2.8 already states.

## Pre-edit search log

No edits were committed, so the NO-NEW-MISMATCH search produced no wording adjustments. Corroborating reads before concluding "no edit":

- `implementation/app.py`, `implementation/serve.py`, `implementation/start.sh`, `implementation/requirements.txt` — confirmed the entry-point split is inert with respect to routing, the envelope, and error mapping.
- `implementation/store.py` — confirmed empty-on-boot, `INITIAL_CLOCK`, and that `order_key` is `(created_at, _seq)`, i.e. `created_at` ascending with insertion order as tiebreaker, consistent with §2.3/§2.10.
- `implementation/routes/testruns.py` (the named single-module reproduction target) — audited `_chamber_peak_load` against §3.3 to rule out a silent logic divergence hiding behind the flake. It matches the PRD verbatim: occupying set is `SCHEDULED`/`PASSED`/`FAILED` on the same `chamber_id` with strict half-open intersection; probes are the requested `window_start` plus every occupying run's start strictly later than it; coverage is start-inclusive/end-exclusive; refusal only when `peak > coupon_capacity`. Likewise the gate order (cert state -> quarantine -> stage -> heat-treat window -> specimens -> chamber capacity), the vacuous-when-no-completed-campaigns temporal gate, `ERR_READING_COUNT_MISMATCH` ahead of the run's own state check, and the void/schedule compensating pair all match the existing prose.
- Grepped `calculations.py`, `services.py`, `validate.py`, `routes/testruns.py` for capacity/coupon/probe logic to confirm the capacity rule lives in exactly one place, so no parallel path could contradict the PRD's single statement of it.

**Conclusion:** the Step 7 sweeps found no PRD ambiguity and no PRD/implementation mismatch. `PRD.md` already uniquely determines the implementation's behavior at every site Step 7 touched, so `PRD_FINALIZED.md` is a verbatim copy — the minimal correct patch is the empty one.

## Step 9: Complete PRD — 2026-09-01T21:36:00.000Z

Done. Verified the completed PRD is a 26-line in-place patch with no structural changes (same 412 lines, no new sections).

## Summary

**Source vs output:** `PRD_FINALIZED.md` (identical to `PRD.md`, 412 lines / 84,960 chars) -> `PRD_COMPLETED.md` (412 lines / 91,287 chars), char delta **+6,327**. 26 paragraphs revised in place; no lines added or removed.

**Counts:** ambiguity-pins **23**, mismatch-revisions **4** (one paragraph carried both).

**Changes**

- §2.1 Roles/Identity — revise — mismatch — `Claimant` X-User-ID must itself name a claimant row (`ERR_CLAIMANT_MISMATCH` pre-lookup) on the three ownership-enforcing endpoints; the claim-lines **listing** performs no identity/ownership check at all; a path claim id is resolved before the ownership comparison (404 wins); X-User-ID is optional for operator roles — `routes/warranty.py:115-131,203-209,234-240`, `validate.py:232-238`
- §2.2 Success envelope — insert — ambiguity — `total_count` is post-filter/pre-page; `has_more` = `offset + len(page) < total_count` — `envelope.py:39-46`
- §2.3 Pagination — insert — ambiguity — non-integer `limit`/`offset` text also yields `ERR_INVALID_PAGINATION` — `validate.py:150-167`
- §2.3 Ordering — insert — ambiguity — equal `created_at` ties broken by server insertion order — `store.py:49-55`
- §2.3 Filters — insert — ambiguity — `mandatory` accepts `true/false/1/0` (else ignored); unknown params ignored; nested collections take pagination only except lot test-runs (`test_type`,`status`) and SKU counterfeit-reports (`status`) — `validate.py:220-229`, `routes/lots.py:192`, `routes/skus.py:167`
- §2.5 Precision/Time — insert — ambiguity — submitted window instants echoed verbatim; server-derived instants rendered ISO-8601 UTC with 3 digits — `serialize.py:75-78,105-107`, `envelope.py:18-24`
- §2.7 Refusal ladder — revise — mismatch — the "claimant ownership" rung is the caller's own identity; the `claimant_id` comparison necessarily follows resolution of the addressed claim — `routes/warranty.py:206-209`
- §2.8 Logical clock — revise — mismatch — the set-clock capability returns `{"current_utc": …}` (not an empty data object), unparseable value -> `ERR_INVALID_REQUEST`, and the clock also mints `created_at`, `updated_at` and `api_request_timestamp` — `routes/clock.py:24-31`, `store.py:58-63`, `envelope.py:27-31`
- §3.1 Catalogue codes — insert — ambiguity — only `sku_code` is length-capped; other unique codes are any non-empty string; `email` gets no syntax check — `validate.py:47-55`, `routes/warranty.py:64`
- §3.1 Lineage — insert — ambiguity — evaluation order is cycle -> family -> depth — `routes/skus.py:22-35`
- §3.1 Amendment — insert — ambiguity — a no-op amendment still re-derives and bumps `version`; omitted `supersedes_sku_id` keeps and re-walks the stored ancestor, explicit null detaches to depth 0 — `routes/skus.py:122-134`
- §3.1 Stock receipts — insert — ambiguity — `units_received` must be at least 1 — `routes/skus.py:143`
- §3.2 Furnace — insert — ambiguity — `max_charge_kg` is a whole number — `routes/shop.py:30`
- §3.2 Campaign — insert — ambiguity — `charge_kg` whole number; `furnace_id` resolved before `lot_id`; absent/non-string window field is `ERR_INVALID_REQUEST`, not `ERR_INVALID_WINDOW` — `routes/shop.py:110-116`, `validate.py:194-210`
- §3.2 Completion — insert — ambiguity — `soak_minutes` has no declared floor, so zero/negative reports `ERR_SOAK_TIME_TOO_SHORT` — `routes/shop.py:181-186`
- §3.3 Test run intake — insert — ambiguity — `chamber_id` existence precedes `lot_id` existence; both chamber applicability rules sit in the request-shape band, after window validation and before lot state — `routes/testruns.py:50-68`
- §3.3 Temporal gate — insert — ambiguity — with no `COMPLETED` campaign the heat-treat window gate is vacuous — `routes/testruns.py:74-78`
- §3.3 Dossier opening — insert — ambiguity — first run on a fresh lot increments the lot's `version` twice (to 3) — `routes/testruns.py:109-113`
- §3.4 Results — insert — ambiguity — an empty `readings` array reports `ERR_READING_COUNT_MISMATCH` — `validate.py:88-95`, `routes/testruns.py:145-147`
- §3.4 Rejection cascade — revise — ambiguity — the lot's `version` increments twice (specimen bookkeeping + rejection) — `routes/testruns.py:162-168`, `services.py:163-179`
- §3.5 Rework — revise — mismatch — `process_status` is set to `MACHINED` unconditionally, moving a `FORGED`/`HEAT_TREATED` lot forward — `routes/lots.py:152`
- §3.6 Pack members — insert — ambiguity — established channel is the earliest member's, and before any member exists it is the `primary_sku_id`'s channel — `routes/packs.py:81-85`
- §3.7 Claim filing — insert — ambiguity — body refs resolved `sku_id` -> `claimant_id` -> `program_id` — `routes/warranty.py:124-126`
- §3.7 Intake score — insert — ambiguity — the 365-day boundary is inclusive — `services.py:134-136`
- §3.9 Cascade link four — revise — ambiguity — fires only from a previously `OPEN` posture (RESTRICTED->SUSPENDED holds nothing); programme `open_hold_count`/`version` updated once **per held claim** — `services.py:195-212`
- §3.9 Suspension withdrawal — insert — ambiguity — pack withdrawal only when the prior posture was not already `SUSPENDED` — `services.py:214-219`

No implementation, test, or scaffold files were touched; `SCAFFOLD*.yaml` and `worklog.md` were not read.
