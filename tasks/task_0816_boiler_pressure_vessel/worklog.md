# Worklog — task_0816_boiler_pressure_vessel

## Step 1: Create task directory — 2026-07-10T08:01:24.344Z

Created `tasks/task_0816_boiler_pressure_vessel/` and `tasks/task_0816_boiler_pressure_vessel/workspace/` (pre-assigned directory, no index auto-scan).

## Step 2: Generate scaffold — 2026-07-10T08:37:27.919Z

All three scaffold artifacts are generated, parse cleanly, and pass `scaffold_lint.py` with `VERDICT: clean lint`. I generated everything purely from the scenario and the skill spec — no sibling task under `tasks/` was read.

## Output files
- `/home/ubuntu/github/CodingPRD/tasks/task_0816_boiler_pressure_vessel/SCAFFOLD.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_0816_boiler_pressure_vessel/SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_0816_boiler_pressure_vessel/SCAFFOLD_CORNER_DESIGN.yaml`

## Design summary (Expert calibration, §0.4)
- **Archetype**: compliance/audit + temporal windowing; **topology**: flat (peer collections joined by FKs, `api_prefix: ""`); **state-machine shape**: parallel (Vessel carries `registration_status` × `service_status`); **role model**: segregation_of_duties; layers: optimistic concurrency, cascading side effects, dual-variant calc, derived-field reconciliation.

## Counts
- **Entities**: 13 (Jurisdiction, InsuranceCompany, Owner, Inspector, Vessel, InsurancePolicy, Inspection, NationalBoardReport, Deficiency, RepairOrder, Certificate, FeeInvoice, IncidentReport)
- **State machines**: 9 rows across 8 distinct entities (Vessel has two parallel-dimension machines; Inspection branching; Deficiency cyclic)
- **Calculations**: 3 (`certificate_fee`, `vessel_risk_score`, `certificate_validity_window`) with 4 variants total (PROVISIONAL/FINAL fee, STANDARD/FORECAST risk)
- **Validations**: 17 (priority-ordered, categories auth→existence→ownership→state→safety→referential→constraint→temporal→fiscal)
- **Endpoints**: 58 (incl. `/_clock/set_current_utc` with default `2026-03-01T00:00:00Z`; OCC-guarded `POST /certificates`)
- **Errors**: 19
- **Roles**: 3 (JurisdictionAdmin opaque; Owner, Inspector entity_backed)
- **Concurrency rules**: 1 (OCC on Vessel.version for certificate issuance)

## §1.8 / §1.9 instance counts
- **§1.8 difficulty design**: 18 instances — 2 per each of the 9 rules, each grounded in §1.1–§1.7 with executable `setup_api_calls` chains and pre-computed literal asserts (fee literals 26338/29026/34400/29025 and per-line-vs-sum rounding delta, risk literals 40/48/100, validity windows verified by code).
- **§1.9 corner design**: 26 instances (23 active + 3 `excluded_because` stubs) across entities/state_machines/calculations/validations/cross_cutting — covering OCC stale-version (412), segregation-of-duties, auth/authz/ownership, not-found, required/enum/duplicate, defaults, pagination, FK reverse lookup, invalid-transition/terminal-lockdown/idempotency, tier and validity boundaries, and coordination/fiscal/repair validations.

Lint result: `398 calls scanned`, `VERDICT: clean lint`; all 44 instance names unique across both design files; no forbidden concurrency vocabulary; design keys correctly isolated to their own files.

Orchestrator verification: all three files `yaml.safe_load` cleanly; SCAFFOLD.yaml = 1666 lines, 58 endpoints.

## Step 3: Copy shared files — 2026-07-10T08:37:35.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0816_boiler_pressure_vessel/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-10T08:45:38.502Z

All checks pass. The PRD is complete and verified.

## Summary

Generated `/home/ubuntu/github/CodingPRD/tasks/task_0816_boiler_pressure_vessel/workspace/PRD.md` for the Boiler & Pressure-Vessel Inspection API.

**Stats**
- Line count: 318
- Endpoints covered: 58/58 (verified — §4 table has exactly 58 rows, matching the scaffold)
- Error catalogue: all 19 error IDs in §5, and every one also surfaces in §2/§3 prose with its trigger condition

**Hard-contract verification (all PASS)**
- **Contract 1 (Field-Name Coverage):** 76/76 real field, request-body, query-param, and path-param identifiers appear verbatim in backticks. (The only "gaps" flagged by extraction were `PROVISIONAL`/`FINAL`/`STANDARD`/`FORECAST`, which are calculation-variant labels, not fields; they appear in prose as intended.)
- **Contract 2 (Rule Coverage):** All 8 state machines (Vessel's parallel registration/service dimensions, Inspector, InsurancePolicy, Inspection fork, Deficiency cyclic loop, RepairOrder, Certificate, FeeInvoice) with every transition, precondition, and side-effect cascade; all 3 calculations (certificate_fee tiered/PROVISIONAL-vs-FINAL, vessel_risk_score STANDARD-vs-FORECAST, certificate_validity_window) rendered as precise prose passing the reconstruction test; the OCC rule (§2.6) naming `expected_vessel_version` + `ERR_STALE_VESSEL_VERSION` 412; and the full priority-1-through-11 validation ordering (§2.7).
- **Contract 3 (§3 Path Purity):** 0 violations — no `/`-prefixed tokens, bare HTTP methods, or method+path combos in §3; endpoints referenced via state-transition/role-verb framing only.

**Structure:** §4 table has the required 4 columns (Method, Path, Description, Authorized Roles); §5 has 2 columns (Error ID, HTTP Status). §2.2 emitted verbatim from the fixed source.

**Deliberately left prose-implicit:**
- The withdraw-deficiency authority check ("only the raising inspector may withdraw") is stated as a rule, but I did not pin it to a specific error ID. The scaffold scopes `ERR_SEGREGATION_OF_DUTIES`'s `applies_to` to reinspect only and assigns no error to the withdraw ownership precondition, so asserting one would contradict the scaffold. The `OPEN`-state precondition on withdraw is mapped to `ERR_INVALID_STATE`.
- Path-parameter names (`vesselId`, `inspectionId`, etc.) are covered once in a §2.4 enumeration rather than repeated per-endpoint, since the flat topology gives each a single meaning.

I did not open either withheld sibling design file (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) or any sibling task directory.

Orchestrator verification: all 58 scaffold (method, path) pairs appear in PRD.md; §4 table has exactly 58 rows.

## Step 5: Generate unit tests — 2026-07-10T09:04:20.825Z

Test infrastructure is complete and verified. Summary:

## Files written

**test_helpers/** (Stage 1 — PRD-specific infrastructure)
- `types.py` — 12 status enums + 5 value enums + `UserRole`; TypedDicts for all 13 entities (`NationalBoardReport` correctly carries only `id`/`created_at` — it's the sole `common_fields: false` entity)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (57 endpoints)
- `api_errors.py` — `ApiErrorId` (19 errors) + HTTP status map, registered with framework
- `constants.py` — fee/risk/validity-window thresholds
- `factories.py` — per-entity input-only payload factories
- `assertions.py` — entity assertions + `assert_same_instant` (instant-based timestamp compare, since PRD §2.4 pins 3 fractional digits and exact-string asserts would be brittle)
- `test_users.py` — opaque `JurisdictionAdmin` shared constant + entity-backed `make_owner_headers`/`make_inspector_headers` builders (identity threading)
- `fixtures.py` — ~20 building-block helpers + composites (`setup_registered_vessel`, `setup_certified_vessel`, `setup_deficiency_in_reinspection`)
- `__init__.py` — barrel export

**test_suite/** (Stage 2 — 59 tests across 7 domain-named files)
- `conftest.py` + `test_01`…`test_07` (registry/vessels, certificate fees, risk scores, lifecycle state machines, cascades, validation precedence, temporal/concurrency/authz)

## Translation results
- **Difficulty queue A: 18/18 instances translated, ≥2 tests each (36 tests).** Every rule_id covered (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).
- **Corner queue B: 23/23 non-stub instances translated, ≥1 test each (23 tests).**
- **3 stubs skipped** (correctly untranslated); all 3 `excluded_because.difficulty_instance` cross-references verified to resolve to real queue-A instances.
- **No instances failed the PRD-first filter** — the PRD covers every asserted rule verbatim (precedence is uniquely derivable from PRD §2.7's explicit total priority order).

## Verification passed
- 59 tests collect cleanly; `test_helpers` imports without error.
- Every one of 65 quoted docstring citations survives a verbatim ≥8-word sliding-window grep of PRD.md (C1); zero fused-ellipsis abbreviations.
- Every test carries exactly one `Design: Difficulty/…` or `Design: Corner/…` tag resolving to a real instance (C4).
- No forbidden "scaffold"/"Table N"/"§1.x" references in emitted code.

Precomputed literal expected values (26338, 29026, 29025, 34400, risk 40/48/100, valid_until instants) were copied verbatim from the design indices, not recomputed. Note: tests were not executed against a live server (no implementation present / out of scope) — they collect and import cleanly and assume the runner supplies `API_BASE_URL`.

## Step 6: Generate implementation — 2026-07-10T09:04:20.825Z

The implementation is complete and fully verified.

## Summary

Built a Python + Flask REST API for the Boiler & Pressure-Vessel Inspection benchmark at `/home/ubuntu/github/CodingPRD/tasks/task_0816_boiler_pressure_vessel/workspace/implementation/`.

### Files written
- `app.py` (~950 lines) — the entire application: logical clock, in-memory stores (empty on boot, no seeding), response envelope, auth/RBAC, all 58 routes, state machines, calculations, and validation ordering.
- `requirements.txt` — `flask`.
- `start.sh` — foreground launcher with guarded pip install (`if ! python3 -c "import flask"`), binds `0.0.0.0:$PORT` (default 10000), `exec python3 app.py`.

### Four verification results
1. **AST parse** — `app.py` (the only `.py` file) passes `ast.parse`. OK.
2. **`app.py` exists** — confirmed.
3. **Route count = 58** — via `app.url_map` (excluding `/static`) and 58 `@app.route` decorators. Every endpoint in the PRD §4 table is routed; the printed rule list matches the table one-for-one with none missing.
4. **`bash start.sh` boots and serves** — booted on a high port, `GET /jurisdictions` returned the correct empty-array envelope, missing-auth returned 401, and `POST /jurisdictions` returned 201. Killed cleanly.

### Key correctness checks exercised end-to-end
- Fee calc: POWER_BOILER (20000) + MAWP tier 12000, per-line ×1.075 round-half-up then summed = 34400. Correct.
- Risk score: base 30 + age_factor 10 − clean_bonus 10 = 30. Correct; STANDARD vs FORECAST diverge after repair completion (std 15, forecast 18 — REINSPECTION excluded from STANDARD only).
- Certificate issuance: OCC (`expected_vessel_version`) rejects stale writes with `ERR_STALE_VESSEL_VERSION` (412); first issuance advances NOT_IN_SERVICE→IN_SERVICE; validity window uses calendar-month addition and jurisdiction override; ledger credited on pay.
- State machines: PASS_WITH_DEFICIENCIES→RESTRICTED, segregation-of-duties on reinspect (409), last-deficiency bubble-up RESTRICTED→IN_SERVICE, and the CRITICAL incident cascade (SUSPENDED + certificate revoked + scheduled non-SPECIAL inspections cancelled + auto-created SPECIAL inspection) all verified.

### Notable interpretation decisions (from PRD-prose fidelity)
- Ownership checks enforced only on the five endpoints the PRD §2.7 / scaffold §1.4 explicitly enumerate (repair-order create/complete, fee-invoice pay, inspection result, incident file) — not on deficiency-raise, NB-report, or repair-order cancel.
- Incident cascade follows PRD §3.8's four steps (no invoice-voiding, which appears only in the scaffold endpoint blurb but not the authoritative §3.8/state-machine).
- Withdraw-by-wrong-inspector mapped to `ERR_OWNERSHIP_MISMATCH` (the PRD frames it as an authorization constraint with no dedicated error id).
- Validation ordering follows PRD §2.7 exactly (auth → authz → path existence → early primitive/enum ERR_INVALID_REQUEST → body-FK existence → ownership → state/OCC → safety → referential → constraint → temporal → fiscal).

Storage is in-memory dicts, reset fresh on every process start, satisfying the per-test-server restart contract.

Orchestrator verification: 58 `@app.route` decorators (== scaffold endpoint count), `app.py` present, `ast.parse` OK, 59 `def test_` across 7 test files.

## Step 7: Run tests and iterate — 2026-07-10T09:20:09.130Z

All 8 rounds are clean. The task is complete.

## Summary

The implementation at `/home/ubuntu/github/CodingPRD/tasks/task_0816_boiler_pressure_vessel` passes the full 8-round stability sweep (two waves of 4) under `per-test-server` isolation: every round is 59/59 passed, 0 failed, 0 errors, 0 skipped. Result files persisted at `workspace/implementation/results.1.json` … `results.8.json`.

- Iterations run: 1 (baseline sweep passed clean; no diagnostic/fix rounds needed).
- Tests deleted: none.
- Fixes applied to `test_helpers/`: none.
- Fixes applied to `implementation/`: none.

Key operational finding (not a code bug): the sweep script's orphan-reaper `pkill -f "task_0816_boiler_pressure_vessel/workspace/implementation"` matches the launching shell's OWN command line (which embeds that same path via `--start-command`), so running it in the same shell as the launch self-terminates the whole sweep with exit 144 and zero output — this masqueraded as a total failure. The runner and app are healthy. Workarounds that worked: reap in a separate shell invocation using the bracket trick (`pkill -f "[t]ask_0816_boiler_pressure_vessel/workspace/implementation"`), and run each wave in the foreground so no stray signal hits a background wrapper. The exit-144 from the earlier background sweep was a post-completion signal to the wrapper, not a test failure — its per-round logs also showed 60/60 passing.

Orchestrator verification: all 8 `results.N.json` show `total=59, passed=59, failed=0, errors=0, skipped=0`.

## Step 8: Finalize PRD — SKIPPED — 2026-07-10T09:20:09.130Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the tests exercised. No `PRD_FINALIZED.md` produced; Step 9 starts from `PRD.md`.

## Step 9: Complete PRD — 2026-07-10T09:26:15.290Z

Done. All edits are in-paragraph pins; no new sections or lines added.

## Summary

- **Source vs completed**: `PRD.md` 317 lines / 50,030 chars → `PRD_COMPLETED.md` 317 lines / 52,864 chars (+2,834 chars; 13 changed lines, all in-paragraph).
- **Counts**: 9 ambiguity-pins, 4 mismatch-revisions.

Changes (each `{section} — {kind} — {type} — {what} — {impl ref}`):

- §2.3 Pagination — insert — ambiguity — `created_at` ties broken by insertion order; non-integer/out-of-bounds `limit`/`offset` → `ERR_INVALID_REQUEST` — app.py:250, 227-245
- §2.7 Validation ordering — revise — mismatch — corrected the "ownership enforced on…" list to add deficiency withdrawal and to state raising/NB-report/repair-cancel/reinspect are deliberately *not* ownership-checked — app.py:1069, 941, 965, 1157, 1035
- §3.1 Inspector commissioning — insert — ambiguity — unmet commission preconditions → `ERR_INVALID_STATE`, checked only on `PENDING→COMMISSIONED` — app.py:556-560
- §3.2 Retire cascade — revise — ambiguity — the ACTIVE-cert revoke on retire runs the full §3.7 cascade (cancel SCHEDULED non-SPECIAL inspections, clear `current_certificate_id`) — app.py:665-668, 355-369
- §3.5 Raise deficiency — insert — mismatch — permitted only while inspection is `SCHEDULED` (else `ERR_INVALID_STATE`); any Inspector may raise (no assigned-inspector check) — app.py:941-947
- §3.5 National Board report — insert — mismatch — any Inspector may file regardless of inspection status; not restricted to the assigned inspector — app.py:963-980
- §3.6 Repair-order cancel — revise — ambiguity — cancel is not restricted to the vessel's owner (any Owner) — app.py:1157
- §3.6 Withdraw deficiency — revise — ambiguity — non-raising inspector → `ERR_OWNERSHIP_MISMATCH`, checked before the OPEN-state check — app.py:1069-1071
- §3.7 Refund — revise — ambiguity — refund while an ACTIVE cert references the invoice → `ERR_INVALID_STATE` — app.py:1244-1246
- §3.7 Certificate issuance / supersedes — insert — ambiguity — supersedes cert only validated as existing + `ACTIVE`; vessel-ownership/current-cert not verified — app.py:1283-1289
- §3.7 Fee-invoice creation — insert — mismatch — creation does not gate on inspection status; FINAL fee computed from current `is_special` + non-withdrawn NON_CRITICAL count — app.py:1177-1189
- §3.8 Incident cascade — insert — ambiguity — auto-created SPECIAL inspection: null `inspector_id`, `scheduled_start`=`scheduled_end`=now, `is_special` true, null `result_recorded_at`, provisional fee = base+tier only — app.py:724-737
- §3.9 Clean bonus — insert — ambiguity — "most recent terminal inspection" = latest `result_recorded_at` (CANCELLED ignored, ties by creation order); "zero attached deficiencies" counts all statuses incl. WITHDRAWN — app.py:297-309

No change was needed for the logical-clock default/`now` semantics, monetary rounding (per-line ROUND_HALF_UP then sum), validity-window months, risk formula, or the certificate OCC/precondition ordering — the existing PRD prose already pins those uniquely to the implementation.

Orchestrator verification: `PRD_COMPLETED.md` exists, 317 lines (same as source), 26 diff lines (13 revised pairs), +2,834 chars.

---

## Pipeline complete — 2026-07-10T09:26:15.290Z

All 9 steps done (Step 8 skipped by its own skip condition). Final state: 59/59 tests passing across all 8 stability-sweep rounds.
