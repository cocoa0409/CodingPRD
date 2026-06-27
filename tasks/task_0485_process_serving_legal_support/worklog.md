# Worklog — task_0485_process_serving_legal_support

Scenario: Process Serving & Legal Support: service request & document, server assignment & territory, attempt log (date/time/GPS) & diligence, service type (personal/substitute/posting) & affidavit, rush/stakeout, skip-trace, county filing/e-file, proof of service.

Difficulty target: Expert

## Step 1: Create Task Directory — 2026-06-24T13:02:57.000Z

Created pre-assigned directory `tasks/task_0485_process_serving_legal_support/` with `workspace/` subdirectory (index pre-assigned by orchestration override; no scan/auto-increment performed).

## Step 2: Generate Scaffold (Expert tier) — 2026-06-24T13:34:33.000Z

Generated the complete three-file Expert-tier scaffold for **task_0485_process_serving_legal_support**. All artifacts pass `scaffold_lint.py` with **`VERDICT: clean lint`** (534 §1.8/§1.9 calls scanned, all 22 FKs reverse-reachable). Files were generated purely from the scenario + skill spec; no sibling task was inspected.

**Complexity profile:** workflow_orchestration × compliance_audit; graph topology; cyclic state machines; segregation_of_duties role model; layers = cascading side effects, dual-variant calculation, rate/threshold triggers, derived-field reconciliation, scheduled actions, optimistic concurrency.

**SCAFFOLD.yaml (§1.0–§1.7):**
- **Entities: 14** — Client, County, Server, ServerTerritory (M:N junction), ServiceRequest (central), Document, Assignment, Attempt, Service, Affidavit, SkipTrace, Stakeout, Filing, InvoiceLine.
- **State machines: 6** (ServiceRequest, Assignment, SkipTrace, Affidavit, Stakeout, Filing) + **1 concurrency rule** (OCC `assignment-create-stale-request` on `ServiceRequest.version`, 412). Two cyclic machines on different entities (ServiceRequest reassign loop; Filing reject→resubmit loop).
- **Calculations: 2** — `service_fee` (tiered per-attempt + rush labor uplift + round-per-line-then-sum; quoted vs final variants on ServiceRequest/Invoice domain) and `server_reliability_score` (realized vs projected variants on Server domain). 4 variant definitions total.
- **Validations: 15** (priority-ordered, categories auth→existence→state→business_safety/temporal/referential/fiscal).
- **Endpoints: 55** (28 POST / 27 GET; high count driven by mandatory FK reverse-reachability GETs across 14 entities, plus a `/_clock/set_current_utc` test-driving endpoint with default `2026-01-01T00:00:00Z`).
- **Errors: 24** domain-specific codes. **Roles: 5** — Admin (opaque), Dispatcher (opaque), Client (entity_backed), Server (entity_backed), Notary (opaque).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8): 18 instances** — all 9 Difficulty Rules × 2 instances, each with full structured `setup_api_calls`/`trigger`/`assert` chains and formula-derived literals computed in code (e.g., final fees 32575/29350/25350/19575/7575; reliability 50.0/33.33).

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9): 45 instances** (36 active + 9 `excluded_because` stubs citing §1.8 by name) across 9 claim-guide sections (entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_complexity_layers, consistency_model).

All 63 instance names are unique across both design files; all `grounds:` refs resolve to declared scaffold elements; no forbidden concurrency vocabulary; no `id` used in business decisions; status enum closure verified.

## Step 3: Copy Shared Files — 2026-06-24T13:34:33.000Z

Copied `INSTRUCTION.md` → `tasks/task_0485_process_serving_legal_support/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-24T13:41:23.000Z

Generated `workspace/PRD.md` for the Process Serving & Legal Support domain (Expert tier). **Structure:** 5 top-level sections, 310 lines.
- §1 Introduction (3 paragraphs)
- §2 Global Specifications — 10 domain-derived subsections (RBAC, fixed §2.2 envelope, pagination, common properties, nested retrieval, validation ordering, monetary precision, logical clock, OCC, cascading consistency)
- §3 Business Logic — 13 lifecycle/process subsections (onboarding, request draft→submit, offer/accept/reassign, attempts & diligence, service & non-est, stakeouts, skip-trace, affidavit & segregation, county filing & e-file window, cancellation cascade, completion & settlement, fee composition, reliability scoring)
- §4 Endpoint table (4 columns, all 55 endpoints)
- §5 Error catalogue (2 columns, all 24 errors)

**Hard Contract reports:** Contract 1 (Field-Name Coverage) PASS — 53/53 entity fields, 17/17 endpoint params. Contract 2 (Rule Coverage) PASS — 15 validations, 1 OCC rule, all 6 state machines, both calculations (quoted/final + realized/projected variants), 24 error IDs, cascades all expressed. Contract 3 (§3 Path Purity) PASS — 406 backtick tokens scanned, 0 paths/methods leaked into §3.

Every scaffold entity (14), state machine (6), calculation (2), validation (15), endpoint (55), error (24), and role (5) is covered in prose. The withheld §1.8/§1.9 design files were not opened.

## Step 5: Generate Unit Tests — 2026-06-24T14:01:33.000Z

Generated complete test infrastructure under a strict design-index-only contract.

### Test files (7 in `test_suite/`)
- `conftest.py` — pytest fixture bridge (api client + 5 role-header fixtures)
- `test_01_fee_calculation.py` — 9 tests (dual-variant quoted/final, tiered attempts, rush labor uplift, round-per-line-then-sum, quoted/invoice-line breakdown, immediate consistency)
- `test_02_reliability_scoring.py` — 3 tests (realized vs projected divergence, fresh-server default)
- `test_03_state_machines.py` — 10 tests (reassign cycle, filing reject/resubmit cycle, initial state, invalid/terminal-state, idempotency, submit/service preconditions)
- `test_04_cascades.py` — 9 tests (depth-4 cancel cascade, depth-3 filing-accept bubble, stakeout/capacity conservation, skip-trace address bubble)
- `test_05_validations.py` — 23 tests (validation-precedence pairs, diligence/empty-set boundaries, e-file/server-active gates, stakeout & filing-window overlap, fiscal/territory/capacity/suspension/deadline guards)
- `test_06_crud_rbac_concurrency.py` — 18 tests (CRUD, county defaults, immutable territory, RBAC denials, OCC stale/valid version, distinct-day dedup, rush deadline)

### Coverage counts
- **Total: 72 test functions, each tagged with exactly one `Design:` line** (72 tags, no untagged/dual-tagged/phantom tags).
- **Queue A (§1.8 Difficulty): 18/18 instances covered, each by ≥2 tests** (36 tags) — all 9 rules × 2 instances.
- **Queue B (§1.9 Corner): 36/36 non-stub instances covered, each by ≥1 test** (36 tags). Bijection verified.

### Instances SKIPPED
**Zero.** Every non-stub instance passed the PRD-first two-condition filter (verbatim coverage + unique derivability). The 9 `excluded_because:` corner stubs were correctly NOT translated; all 9 difficulty cross-references resolve.

### test_helpers/ files created (9)
`__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`

### Validation performed
All modules compile; full package imports; all 72 tests collect under pytest. Every test_suite→test_helpers import resolves. Verbatim PRD-citation pass: distinctive substrings of every cited sentence grep-match `PRD.md`. No skip/skipif/xfail; no scaffold leakage; entity-backed roles thread real entity ids; all fixtures build state from scratch via API; temporal assertions use default logical clock. All formula literals independently re-derived (quoted 7575, final 32575, mode_a 29350, mode_b 25350, cancel 19575→7575, reliability 50.0/33.33).

## Step 6: Generate Implementation — 2026-06-24T14:01:33.000Z

**Files in `workspace/implementation/`** (13 files): `start.sh`, `requirements.txt` (`flask>=2.0`), `app.py` (entry point, all 55 routes, error handlers, validation precedence), `db.py` (in-memory store), `clock.py` (logical clock default `2026-01-01T00:00:00Z`), `errors.py` (24-code catalogue), `response.py` (envelope), `auth.py` (5-role RBAC), `validate.py`, `timeutil.py`, `fees.py` (`service_fee` quoted/final + `server_reliability_score` realized/projected, Decimal/ceil), `services.py` (invoice-line mgmt, recompute, cascades), `serializers.py`.

**Endpoints implemented: 55** (all PRD §4 including `/_clock/set_current_utc`).
**start.sh:** reads `$PORT` (default 10000), binds `0.0.0.0`, runs foreground via `exec python3 app.py`. Verified foreground hold, SIGTERM stop, state-wipe on restart.
**Storage:** in-memory only — no SQLite/JSON/tmp, no seeding/preloading; every entity via API; fresh process wipes all state.
**Logical clock:** default `2026-01-01T00:00:00Z`; all temporal logic reads it. Verified non-rush deadline = created+30d.
**Validation precedence:** auth(401)→authz(403)→existence(404)→well-formedness(422)→stale_version(412)→invalid_state(409)→business rules. All §1.8 values reproduced (final fees 32575/29350/25350/19575/7575; quoted 7575/7550; reliability 50.0/33.33; depth-4 cancel cascade; filing reject→resubmit reject_count=1). 57/57 self-test checks pass.

**PRD ambiguities resolved with a concrete choice:**
1. **Future-dated attempts.** PRD §3.4 says `attempted_at_utc` must be "no later than current logical clock," but declared test setups log attempts dated after the default clock with no clock-set and assert success, and no error code exists for future-dated attempts. Chose to accept the supplied timestamp (format-validated only) rather than reject.
2. **ATTEMPT invoice line materialization.** Chose to maintain a single ATTEMPT InvoiceLine per request synced to current tiered value on every recompute (created once a non-zero charge accrues), so both line-breakdown reads and `final_fee == sum(non-voided lines)` invariant (non-rush) hold. Rush uplift folded into `final_fee` but not materialized as a line.
3. **Accept-on-superseded ordering.** Chose to check `superseded` before the generic OFFERED-state check in `/accept` so a superseded offer returns `ERR_ASSIGNMENT_SUPERSEDED` (not `ERR_INVALID_STATE`), while a non-superseded non-OFFERED assignment still returns `ERR_INVALID_STATE`.

## Step 7: Run Tests and Iterate — 2026-06-24T14:06:07.000Z

**Iterations run:** 2 full 8-round parallel stability sweeps (16 rounds total). Every round passed 72/72 with zero failed, errored, or skipped tests.

**Outcome:** The task `task_0485_process_serving_legal_support` was already in a clean, stable passing state. No diagnostic protocol steps were triggered because the union of failing tests across all rounds was empty.

**Tests deleted:** None — no test failed unique-derivability or coverage checks because none failed at all.
**Fixes applied to test_helpers/:** None.
**Fixes applied to implementation/:** None.

**Notes:**
- An early misread (parsing results JSON with key `outcome` instead of the actual key `status`) produced a spurious "FAIL" list in the first inspection. The underlying results were green from the first sweep; the JSON schema uses `status` (values `passed`/etc.) and top-level `passed`/`total`/`failed`/`errors`/`skipped` counters, all confirming 72/72 passing.
- Implementation is in-memory only (`db.py` plain Python dicts, no file/SQLite/JSON persistence, no startup seeding); `start.sh` re-invocation wipes all state. Logical clock defaults to `2026-01-01T00:00:00Z`.
- `start.sh` installs deps only when missing (avoids boot contention under 8× concurrent peak), runs foreground on `$PORT`/`0.0.0.0`.

Final 8-round sweep verified by orchestrator: results.1–8.json all 72/72, failed=0 errors=0 skipped=0.

## Step 8: Finalize PRD — SKIPPED — 2026-06-24T14:06:07.000Z

Skipped per skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes (zero iterations beyond baseline). `PRD.md` already determined every behavior the implementation exhibits at the Step 7 fix sites, so no `PRD_FINALIZED.md` is produced. Step 9 (full completeness scan) still runs.

## Step 9: Complete PRD — eliminate residual ambiguity/mismatch — 2026-06-24T14:16:11.000Z

`PRD_FINALIZED.md` did not exist, so copied `PRD.md` → `PRD_COMPLETED.md` and edited only the copy. Implementation walked exhaustively across `app.py`, `services.py`, `fees.py`, `serializers.py`, `validate.py`, `auth.py`, `timeutil.py`, `clock.py`, `response.py`, `db.py`, `errors.py`; tests used only as auxiliary cross-reference.

**Line counts:** PRD.md = 310 lines / 48,257 chars; PRD_COMPLETED.md = 310 lines / 50,745 chars. Char-delta = **+2,488** (line count unchanged — every edit is an in-paragraph insert/revision).

**Counts:** ambiguity-pins = **6**, mismatch-revisions = **2**.

**Changes:**
- §2.1 RBAC — insert — ambiguity — pinned that read ownership-scoping applies only to the `Client` role; `Server`/`Notary`/`Admin`/`Dispatcher` reads are not ownership-filtered (per-resource `server_id`/declarant checks gate only mutations) — app.py:317-319, 327, 375, 486, 591, 681, 971-972.
- §2.6 Validation Ordering — insert — ambiguity — pinned that supplied-but-negative optional integer policy fields (`min_diligent_attempts`/`filing_fee_cents`/`max_concurrent_filings`/`max_active_assignments`) and booleans-where-integer-expected yield `ERR_INVALID_REQUEST` — validate.py:55-61,73-81; app.py:163-165,202.
- §3.1 Onboarding (ServerTerritory) — insert — ambiguity — pinned that a duplicate `(server_id, county_id)` create is idempotent: returns the existing row with 201, no error — app.py:252-254.
- §3.3 Accept ordering — insert — ambiguity — pinned that the supersession guard (`ERR_ASSIGNMENT_SUPERSEDED`) is checked first, ahead of the `OFFERED`-state check, taking precedence over `ERR_INVALID_STATE` — app.py:718-722.
- §3.4 Field Attempts — revise — mismatch — PRD claimed `attempted_at_utc` must be ≤ logical clock and within the assignment's `ACTIVE` lifetime; impl enforces neither (format-validated only, future-dated attempts succeed). Revised to match — app.py:790-795.
- §3.5 Recording Service — insert — ambiguity — pinned that `recipient_relation` is optional on all service types (incl. `SUBSTITUTE`), defaults to empty string when omitted/null, and a non-string value yields `ERR_INVALID_REQUEST` — app.py:525-529.
- §3.9 County Filing — insert — ambiguity — pinned that Filing create imposes no `SERVED`/`NOTARIZED` precondition (those gates are submit-only); the only structural check is affidavit-belongs-to-request, else `ERR_NOT_FOUND` — app.py:1037-1039.
- §4 Endpoint table (`GET /filings`) — revise — mismatch — PRD listed only `county_id`/`affidavit_id` filters; impl also supports `status`. Added it — app.py:1074-1075.

---

## Pipeline Complete — 2026-06-24T14:16:11.000Z

All 9 steps finished. Final deliverable: a passing Expert-tier PRD benchmark task.
- **Tests:** 72/72 passing across 16 stability rounds (two 8-round parallel sweeps), 0 deletions/weakenings.
- **Artifacts:** SCAFFOLD.yaml + SCAFFOLD_DIFFICULTY_DESIGN.yaml + SCAFFOLD_CORNER_DESIGN.yaml, workspace/PRD.md, workspace/PRD_COMPLETED.md (PRD_FINALIZED.md intentionally absent — Step 8 skipped), workspace/implementation/ (13 files, in-memory Flask), test_helpers/ (9 files), test_suite/ (7 files, 72 tests).
