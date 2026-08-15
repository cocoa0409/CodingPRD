# Worklog — task_1347_model_risk_management_validation

## Step 1: Create Task Directory — 2026-08-12T23:43:00.000Z

Pre-assigned and pre-created per command args: `tasks/task_1347_model_risk_management_validation/` with `workspace/` subdirectory. Verified existing; no other task_* directory touched.

## Step 2a: Repair SCAFFOLD.yaml (resume salvage) — 2026-08-13T00:31:00.000Z

Resume run found SCAFFOLD.yaml (1130 lines) and SCAFFOLD_DIFFICULTY_DESIGN.yaml present; SCAFFOLD_CORNER_DESIGN.yaml missing. SCAFFOLD.yaml failed YAML parse with exactly 4 errors, all the same pattern — unquoted `trigger:` values containing flow maps (lines 266/276/296/305, the `decide {decision: APPROVE|REJECT}` triggers for ModelDocumentation and ChangeRequest). Fixed by double-quoting those 4 scalar values (matching the file's own idiom at line 285). Post-repair validation: YAML parses; top-level keys = scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities[10], state_machines[9], concurrency_rules[1], calculations[6], validations[11], endpoints[33], errors[34], roles[5]; no `scaffold_difficulty_design`/`scaffold_corner_design` keys present. File ends with complete role table (TestHarnessOperator) — not truncated. Kept and reused; not regenerated.

## Step 3: Copy Shared Files — 2026-08-13T00:32:00.000Z

Copied ./INSTRUCTION.md → tasks/task_1347_model_risk_management_validation/workspace/INSTRUCTION.md.

## Step 2b: Generate SCAFFOLD_CORNER_DESIGN.yaml (resume completion) — 2026-08-13T01:03:00.000Z

**Generated**: `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`, 116 total instances.

**Instance counts per section** (active / excluded_because stubs):
- entities: 20 / 0
- state_machines: 17 / 18 (stubs cover corners already asserted by §1.8: suspend/resume cycle, retest cycle, escalation cascade, 3-breach auto-finding, both overlap rules, both priority pairs, retire-replacement gate, and the §1.8-owned calculation/boundary/invariant claims)
- calculations: 13 / 0
- validations: 24 / 0
- endpoints: 6 / 0
- errors: 1 / 0 (the section is primarily a triggerability cross-check; the comment block maps all 33 §1.6 error_ids to their covering instance in this file or §1.8)
- rbac: 9 / 0
- cross_cutting_complexity_layers: 6 / 0
- consistency_model: 2 / 0

**Total: 98 active instances + 18 excluded_because stubs.** Every stub's `difficulty_instance` was verified to exist by name in SCAFFOLD_DIFFICULTY_DESIGN.yaml.

**§1.5 gaps found**: none. Every setup chain replays against the existing §1.5 surface — the clock endpoint covers all time-gated setups, and OCC `expected_model_version` values are always bound to a `${var}` captured from a prior create/GET (never a bare literal). No scaffold edits were needed; SCAFFOLD.yaml and SCAFFOLD_DIFFICULTY_DESIGN.yaml are untouched.

**Replay bugs caught and fixed during authoring**:
- `clock_sweep_overdue_boundary_exactness`: model was LOW (TIER_3 → CRITICAL due 28d) while clock calls straddled a 14-day boundary; changed the model to HIGH (TIER_1 → due 14d = 2026-08-15, grace ends 2026-08-22) to match the pinned clock positions.
- `escalated_high_finding_on_tier2_does_not_suspend`: original draft had a self-contradictory assert with a "fix this later" note; rewrote with correct arithmetic (TIER_2 HIGH due = 45d = 2026-09-15, escalation at now > 2026-09-22, clock to 2026-09-23).
- `immediate_consistency_visible_in_same_response`: corrected HIGH-on-TIER_3 deadline literal to 2026-09-30 (60 days).
- Two illegal `excluded_because` stubs citing §1.9 siblings instead of §1.8 instances were removed and replaced with a proper errors-section cross-check.
- YAML flow-mapping breaks (`$.data[0].id`, `grounds: [errors[ERR_X]]`) fixed by quoting.

**Validation**: `yaml.safe_load` passes, and `scaffold_lint.py` reports `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (667 calls scanned). All 116 corner-design names are unique and disjoint from the 18 difficulty-design names; zero unbound `${var}` placeholders across all instances.

## Step 4: Generate PRD — 2026-08-13T01:16:00.000Z

All audits pass. The PRD has been generated and written to `workspace/PRD.md` (281 lines). The withheld difficulty/corner design files were never opened.

## Section list with line counts

| Section | Lines |
|---|---|
| # Title | 2 |
| ## 1. Introduction (2 paragraphs: business context, then system scope) | 6 |
| ## 2. Global Specifications — 9 subsections: 2.1 RBAC (16), 2.2 API Response Structure verbatim block (49), 2.3 Pagination (4), 2.4 Resource Identity/Timestamps/Versioning incl. MetricReading append-only exception (4), 2.5 Logical Clock & Sweeps (6), 2.6 OCC (4), 2.7 Precision/Rounding (4), 2.8 Request Validation Pipeline — 11 stages (16), 2.9 Segregation of Duties & Ownership (6) | 111 |
| ## 3. Business Logic — 9 subsections: 3.1 Registration & Risk Tiering (10), 3.2 Documentation (6), 3.3 Change Control under OCC (6), 3.4 Validation Engagements & Retest Loop (8), 3.5 Approval & Vendor Transparency (6), 3.6 Findings/Deadlines/Escalation (12), 3.7 Monitoring/Readings/Breaches (12), 3.8 Suspension/Resumption/Retirement (10), 3.9 Board & Regulatory Reporting (10) | 82 |
| ## 4. Endpoint Definitions (intro paragraph + 4-column table, 33 rows) | 40 |
| ## 5. Error Code Catalogue (2-column table, 34 rows) | 40 |

**Total: 281 lines.**

## Coverage audit results

**Contract 1 — Field-Name Coverage: PASS.** 77 required identifiers (all 10 entities' fields including common fields, endpoint-only inputs `decision`/`expected_model_version`/`replacement_model_id`/`to_iso8601`/`current_utc`, query params `limit`/`offset`/filters, path params `docId`/`crId`/`fid`) — 77 present in backticks, 0 missing (verified mechanically against fence-stripped text).

**Contract 2 — Rule Coverage: PASS (manual walk of all six categories plus tail).**
- Validation priority ordering: expressed as the explicit 11-stage pipeline in §2.8 (headers → body shape → role → existence → OCC → ownership → state → safety → temporal → referential → constraint, earlier masks later), plus endpoint-local orders in §3.2 (state before SoD), §3.3 (OCC after existence, before state), §3.4, §3.5 (state → safety/vendor-before-temporal → temporal → referential), §3.7, §3.8 (existence → state → referential → constraint — corrected during audit).
- OCC rule: `expected_model_version` required on change-request creation, mismatch → `ERR_STALE_VERSION` (412); no time-overlap framing; no other endpoint takes a version field.
- All 24 state transitions across 9 state machines expressed with preconditions + error IDs + side effects; all cross-entity cascades stated (escalation → suspension → metric pause; closure → count/risk/auto-resume; retirement → finding transfer with deadline recomputation against replacement tier, count/risk recomputation on both models; completion → model field updates; reopen non-reversion).
- All 6 calculations in precise prose (no pseudocode, no fuzzy words — mechanically verified zero operator/`AND`/`OR`/`min(` leaks and zero hedging words): risk score with both variants and tier boundaries 70/40, deadline formula (90/60/30/14 bases, 1.0/1.5/2.0 tier multipliers, round-half-up on multiplication only, −5 monitoring deduction, 7–365 clamp, tier pinned before self-counting), inventory risk index (both variants, pinned single-final-rounding order, 0.00 empty-set rule), revalidation schedule (6/12/24 months, 3-month MAJOR compression), consecutive-breach escalation (strict comparison, equality never breach, fires only at exactly 3), open-findings count.
- Sibling-branch symmetry verified (dual retire transitions, three close transitions, dual decommission transitions, APPROVE/REJECT, both aggregation variants, both score variants).
- All 34 error IDs appear in §2/§3 narrative, not only the §5 table; all 43 enum/state values appear as exact strings; §2.2 confirmed byte-identical to `section-2.2-response-structure.md`.

**Contract 3 — §3 Path Purity: PASS.** 420 backtick tokens scanned in §3: 0 starting with `/`, 0 bare HTTP methods, 0 method+path combinations. Endpoints are referenced via state-pair framing, role + verb, or capability description.

Output file confirmed written: `workspace/PRD.md`, ending at §5 with no audit footer.

## Step 6: Generate Implementation — 2026-08-13T01:50:00.000Z

Implementation complete and verified. All files live under `workspace/implementation/`.

## File list
- `start.sh` (executable) — guarded pip install (`if ! python3 -c "import flask"`), then `exec python3 app.py`
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask assembly, `before_request` auth, `ApiError`/404/405/500 envelope handlers, `app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))`
- `db.py` — in-memory `Store` singleton (empty dicts per entity, RLock, insertion sequence, logical clock default `2026-08-01T00:00:00Z`)
- `errors.py`, `response.py`, `middleware.py`, `validate.py`, `serializers.py` — error type, envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination in `meta`), X-User-ID/X-User-Role auth + role gates, stage-2 body validators, entity serializers
- `services/risk.py` — risk score (DEV_DECLARED ×20 / VALIDATOR_ASSESSED ×25), tier derivation, `finding_deadline_days` (Decimal round-half-up on tier multiplier only, −5 MONITORING, clamp [7,365]), `inventory_risk_index` (Decimal, single final round-half-up to 2dp), breach strictness
- `services/workflow.py` — `mutate()` (version++/updated_at), finding creation with pinned tier, suspend/resume cascades, clock sweep
- `routes/` — `models.py`, `documentations.py`, `change_requests.py`, `engagements.py`, `findings.py`, `monitoring.py`, `vendor.py`, `reports.py`, `clock.py`

## Logical clock and sweeps
- Clock lives in `db.Store` (`clock_dt` + `clock_raw`); startup default is exactly `2026-08-01T00:00:00Z`, never wall-clock. Every "now" (created_at, completed_at, escalated_at, deadline anchoring, report snapshot time, `meta.api_request_timestamp`) reads the logical clock. `POST /_clock/set_current_utc` (PlatformAdmin) parses `to_iso8601`, stores it, echoes the supplied string verbatim as `current_utc`, then runs the sweep.
- Sweep (`workflow.run_sweep`), all strict `>` comparisons: pass 1 OPEN→OVERDUE when `now > remediation_due_at`; pass 2 OVERDUE→ESCALATED when `now > due + 7d` (a finding jumped past both boundaries lands ESCALATED in one sweep, stamping `escalated_at`); escalation of a HIGH/CRITICAL finding on a TIER_1 APPROVED_FOR_USE model suspends it and pauses its ACTIVE metrics; CURRENT vendor assessments with `now > valid_until` flip to EXPIRED (equality stays CURRENT).

## Storage design
Purely in-memory: one module-level `Store` with plain dicts keyed by UUID, created fresh per process — no seeding, no disk, no external services. Concurrent requests serialized with a single `threading.RLock`. Derived fields (`open_findings_count`, `monitoring_posture`) are computed from the store at serialization; `risk_score`/`risk_tier`/`validation_due_at` are stored and recomputed only at the PRD-defined trigger points.

## Endpoint count
All **33** endpoints from the PRD §4 table are implemented (models 5, documentations 3, change requests 3, engagements 4, findings 4, monitoring 6, vendor 2, reports 4, clock 1), with the §2.8 pipeline ordering enforced per endpoint (headers → body shape → role → existence left-to-right → OCC `expected_model_version` → ownership → state → safety/SoD → temporal → referential → constraint) and the exact error IDs/HTTP codes from the catalog.

## Verification
Booted via `bash start.sh` (reads `$PORT`, binds `0.0.0.0`, foreground `exec`) and ran a ~60-assertion live smoke suite covering: auth/role/body precedence, risk scoring both variants, tier boundaries, OCC 412 flow, doc SoD + supersede, half-open engagement window adjacency, strict breach equality, 3rd-consecutive-breach auto-finding (title/25-day deadline/system attribution), sweep overdue/escalation/suspend/pause, retest-gated close + auto-resume, reopen deadline preservation, vendor gate (score ≥ 70, expiry), MAJOR CR compression to now+3mo, retirement transfer with deadline recomputation against the replacement's pinned tier, report snapshots (both aggregation variants, empty-set 0.00), closed-interval report overlap, and pagination meta. All checks pass (the only failures seen were arithmetic mistakes in my throwaway script's expectations, e.g. 120 days from 2026-09-03 = 2027-01-01, and MEDIUM-severity escalations correctly not suspending a model).

## Step 5: Generate Unit Tests — 2026-08-13T01:56:00.000Z

Generation complete. Summary:

## Test counts
- **Queue A (Difficulty): 34 tests** — 17 of 18 instances translated, 2 tests each.
- **Queue B (Corner): 98 tests** — all 98 non-stub instances translated, 1 test each. The 18 `excluded_because:` stubs were not translated; every stub's `difficulty_instance` cross-reference was verified to resolve to a real §1.8 instance.
- **Total: 132 tests** across 11 files.

## Instances skipped (two-condition filter)
- **`Difficulty/boundary_precision_check/risk_score_exactly_70_lands_tier_1`** — skipped. Its two setup payloads are byte-identical (`MEDIUM` / `MULTI_DESK` / exposure 500000), so the PRD formula (20×2 + 10×1 + 10×1 = 60) uniquely derives risk_score **60 / TIER_2 for both** models; the instance asserts 70/TIER_1 for the first. No PRD-only reader can derive 70 from those inputs — the asserted outcome is not uniquely derivable (it in fact contradicts PRD §3.1). Gap left as a gap: no placeholder, no weakened assertion.

## Recipe correction (PRD-first, claim preserved)
- `model_suspend_resume_cycle_restores_approved` (queue A): the yaml's setup completes the only engagement at logical 2026-08-01 but creates the CRITICAL finding at 2026-08-02, so PRD §3.6's retest gate ("`completed_at` is after the finding's `created_at`") would make the asserted close fail with ERR_RETEST_REQUIRED. The cycle claim itself is fully PRD-covered, so the fixture adds a retest engagement completed at 2026-08-24 — exactly as the sibling instance `suspend_resume_conserves_metric_activation` already does — making the asserted close reachable.

## Deliberate assertion-form decisions
- Timestamps are asserted as **instants** (parse-and-compare via `assert_instant_equal`), not raw strings: the PRD pins the instant each rule produces and mandates three-fractional-digit ISO 8601 rendering, so string equality against the yaml's no-millis literals would fail a conformant `.000Z` serializer (two-reader test).
- `version` initial value is never asserted absolutely (PRD states only "increments on every mutation" / "+1 per change-request create/decide"); tests assert integer presence and relative +1 increments instead.

## Files
**test_helpers/**: `__init__.py` (barrel: framework re-exports + PRD-specific), `types.py` (9 entity TypedDicts — MetricReading correctly omits `updated_at`/`version`, 20 enums), `api_client.py` (33 endpoint methods), `api_errors.py` (35 error IDs + HTTP map registered via `set_error_http_status_map`), `assertions.py` (per-entity shape assertions, instant comparison, tier invariant), `factories.py`, `constants.py` (deadline/tier/revalidation/breach constants), `test_users.py` (7 opaque-id header sets + per-id builders), `fixtures.py` (composite chains: approvable/approved models, TIER_1 suspension-via-clock-sweep, retired pairs, breach-run accumulation, report builders).

**test_suite/**: `conftest.py` + `test_01_model_registration_risk.py` (11), `test_02_documentation.py` (5), `test_03_change_control_occ.py` (10), `test_04_validation_engagements.py` (12), `test_05_model_approval_gates.py` (11), `test_06_findings.py` (14), `test_07_monitoring_breaches.py` (15), `test_08_suspension_retirement.py` (15), `test_09_reporting.py` (13), `test_10_security_rbac.py` (15), `test_11_listings_envelope_consistency.py` (11).

## Design-tag confirmation
Audited programmatically: all 132 tests carry **exactly one** `Design:` line as the final docstring line; every tag resolves verbatim to a real instance `name:` in the cited queue's yaml (34 `Difficulty/...`, 98 `Corner/...`); no stub tags used; no untagged tests; no `pytest.mark.skip`/`skipif`/`xfail`; no "scaffold" references in generated code; all 180 quoted PRD citation spans verified verbatim against PRD.md (0 failures); all modules compile and import cleanly.

## Step 7: Run Tests and Iterate — 2026-08-13T02:40:00.000Z

ALL 8 ROUNDS PASS. 132/132 × 8 = 1056/1056.

The fix was removing the redundant `python3 -c "import flask"` check from start.sh. That check was spawning an extra Python interpreter on every server boot, which under 8-round concurrent load was pushing some boots past the 15s restart-poll window in `pytest_plugin._restart_server`.

**Iterations run:** 2 (the initial sweep that exposed the flakiness, plus the verification sweep with the fix).

**Tests deleted:** None. All 132 tests have verbatim PRD coverage and unique derivability — the failures were infrastructure flakiness (server restart timeouts), not test assertions tripping.

**Fixes applied to `test_suite/`:** None.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `implementation/`:**
- `workspace/implementation/start.sh` — removed the per-boot `python3 -c "import flask"` probe. Under the 8-round concurrent sweep (≈1056 server restarts total), that probe spawned an extra Python interpreter per restart; the cumulative CPU contention pushed some boots past the runner's 15s restart-poll window, surfacing as spurious "could not be restarted" errors. Replacing the probe with a direct `exec python3 app.py` cut boot latency from ~0.5s+ to ~0.3s typical and eliminated the timeouts. Solo-round duration dropped from ~152s to ~91s.

**Final sweep result:** 8 rounds × 132 tests = 1056/1056 passed.

## Step 8: Finalize PRD — 2026-08-13T02:44:00.000Z

`PRD_FINALIZED.md` produced at `workspace/PRD_FINALIZED.md` — a verbatim copy of `PRD.md` with zero edits.

## Line counts and delta

- `PRD.md`: 281 lines
- `PRD_FINALIZED.md`: 281 lines
- Delta: 0 lines, 0.0% — byte-identical (`diff -q` clean)

## Changes

**None.** The `<step_7_diff>` contains exactly one fix, and it does not trace to any PRD silence or PRD/impl mismatch:

- **`workspace/implementation/start.sh`** — removal of the per-boot `python3 -c "import flask"` probe. This is pure launcher infrastructure: the probe was a no-op dependency sanity check whose only effect was boot latency (~0.5s+ → ~0.3s). Step 7 explicitly states the failures were "infrastructure flakiness (server restart timeouts), not test assertions tripping," with no test deletions and no `test_suite/`/`test_helpers/` fixes. The PRD governs API behavior (endpoints, envelopes, business rules); the start.sh boot contract lives in `INSTRUCTION.md`, not the PRD. No observable API behavior changed, so there is nothing for the PRD to pin.

## Per-edit pre-edit search log

One candidate edit was considered (pinning the start.sh boot behavior) and rejected after the mandatory search:

- **(a) Subject identified:** server boot sequence — whether the PRD should pin anything about the `import flask` probe or the direct `exec python3 app.py` launch.
- **(b) Impl paths enumerated and read/grepped:** `implementation/start.sh` (read in full, lines 1-9 — confirmed it is a 4-line launcher ending in `exec python3 app.py`); `implementation/app.py` (grepped for `import flask` / `subprocess` / `check` — no hits, confirming the probe never touched application code); full `implementation/` listing reviewed (`app.py`, `db.py`, `errors.py`, `middleware.py`, `response.py`, `routes/`, `services/`, `serializers.py`, `utils.py`, `validate.py`) — no boot-probe coupling anywhere.
- **(c) Wording adjustment:** no edit committed. Adding wording about the launch sequence would (i) trace to no PRD silence on API behavior — the probe's presence or absence is invisible to every endpoint — and (ii) risk violating the NO-NEW-MISMATCH RULE by inventing a requirement (e.g., "server boots via `exec python3 app.py` with no pre-flight checks") that over-specifies infrastructure the PRD deliberately leaves to the build contract in `INSTRUCTION.md`.

Per the HARD SCOPE, edits must trace to a step_7_diff fix that reveals PRD-silence or PRD-mismatch; the sole fix here is a performance fix to launcher plumbing with zero behavioral surface, so the minimal correct patch is the empty patch.

## Step 9: Complete PRD Scan — 2026-08-13T02:55:00.000Z

Done. PRD_COMPLETED.md is written and verified against the diff.

**Files:** `workspace/PRD_FINALIZED.md` (281 lines, 43,146 chars) → `workspace/PRD_COMPLETED.md` (284 lines, 45,933 chars). Delta: +3 lines, +2,787 chars.

**Counts:** 19 ambiguity-pins, 2 mismatch-revisions (21 changes total; no new sections, all in-paragraph edits).

**Changes:**

- §2.1 — revise — mismatch — ModelValidator bullet narrowed from "may never act on a model they own" to "may never open a validation engagement on a model they own (§2.9)"; completion/reopening and finding-raising carry no ownership restriction — impl `routes/engagements.py:44` (SoD only at creation), `routes/engagements.py:108-171` and `routes/findings.py:25-40` (no identity/SoD checks).
- §2.2 — insert — ambiguity — `api_request_timestamp` pinned as stamped from the logical clock, not wall-clock — impl `response.py:16-20`.
- §2.2 — insert — ambiguity — unmatched paths/unsupported methods yield `ERR_NOT_FOUND` (404) in the standard envelope with the header check still running first; unexpected failures yield `ERR_INTERNAL` (500) — impl `app.py:23-33`, `middleware.py:21-31`.
- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` are clamped to the nearest bound, not rejected; non-integer values yield `ERR_INVALID_REQUEST` — impl `validate.py:88-108`.
- §2.3 — insert — ambiguity — `total_count` counts all filter-matching records pre-pagination; `has_more` true iff `offset` + returned records < `total_count` — impl `response.py:28-34`.
- §2.3 — insert — ambiguity — sort ties on equal `created_at` (or `observed_at` for readings) broken by insertion order — impl `_seq` tiebreak in all list routes, `db.py:37-39`.
- §2.3 — insert — ambiguity — filters are exact-match equality; a non-matching filter value yields an empty page, not an error — impl e.g. `routes/models.py:78-85`.
- §2.4 — insert — ambiguity — `version` starts at 1; `updated_at` equals `created_at` at creation — impl e.g. `routes/models.py:53-55`.
- §2.5 — revise — ambiguity — clock endpoint "advances" → "sets": any valid ISO 8601 instant accepted (no forward-only constraint), and `current_utc` echoes the supplied `to_iso8601` string verbatim — impl `routes/clock.py:13-24`, `db.py:32-35`.
- §2.7 — insert — ambiguity — the 2-decimal inventory risk index is a JSON number, so trailing zeros are not preserved (0.00 emitted as `0.0`) — impl `services/risk.py:143`, `serializers.py:172`.
- §2.7 — insert — ambiguity — calendar-month addition (used for `validation_due_at` and `valid_until`) clamps day-of-month to the target month's length — impl `utils.py:41-46`.
- §2.7 — insert — ambiguity — request-body timestamps may carry any numeric offset or none (naive → UTC), normalized to UTC — impl `utils.py:12-26`.
- §2.8 — insert — ambiguity — stage 2 also requires the request body itself to be a JSON object where the endpoint declares fields — impl `validate.py:18-24`.
- §3.2 — revise — mismatch — absent/non-boolean evidence flag → `ERR_INVALID_REQUEST` (400, stage 2); only present-but-false flags → `ERR_DOCUMENTATION_INCOMPLETE` (409), evaluated after ownership and retired-state gates — impl `validate.py:43-47`, `routes/documentations.py:35-40`.
- §3.4 — insert — ambiguity — any `ModelValidator` may complete or reopen an engagement; not restricted to the opener; independence gate applies only at opening — impl `routes/engagements.py:108-171`.
- §3.5 — insert — ambiguity — recording a vendor assessment on a retired model fails with `ERR_MODEL_ALREADY_RETIRED`, evaluated before the vendor-only gate — impl `routes/vendor.py:24-31`.
- §3.6 — insert — ambiguity — `escalated_at` stamped with the logical-clock now — impl `services/workflow.py:106`.
- §3.6 — insert — ambiguity — the sweep runs its overdue pass before its escalation pass, so one sweep can carry a finding `OPEN` → `OVERDUE` → `ESCALATED` when both thresholds are past — impl `services/workflow.py:96-107`.
- §3.6 — insert — ambiguity — `closed_at` stamped with the logical-clock now — impl `routes/findings.py:91`.
- §3.7 — insert — ambiguity — reading `value` pinned as numeric — impl `validate.py:67-75`, `routes/monitoring.py:93`.
- §5 — insert — ambiguity — added `ERR_INTERNAL | 500` row to the error catalogue — impl `app.py:31-33`.

Everything else in the implementation (all 29 endpoints, gate ordering per §2.8, scoring/tier formulas, deadline formula with tier pinning, OCC semantics, retire transfer mechanics, report snapshot fields, breach auto-raise at exactly 3, role table, and the remaining error catalogue) was already uniquely pinned by the PRD and required no change.
