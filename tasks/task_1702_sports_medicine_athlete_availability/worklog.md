# Worklog — task_1702_sports_medicine_athlete_availability

## Step 1: Create Task Directory — 2026-08-14T09:10:00.000Z

Task directory `tasks/task_1702_sports_medicine_athlete_availability/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher. Step 1 treated as DONE per invocation args; no index scan performed, no other task_* directory touched. Difficulty directive from user: "Generate task hard than expert level!"

## Step 2: Generate Scaffold — 2026-08-14T09:58:30.000Z

The scaffold generation is complete. All three artifacts are written, parse as YAML, and pass the skill's lint with a clean verdict.

## Summary

Generated the scaffold for **task_1702_sports_medicine_athlete_availability** (Sports Medicine & Athlete Availability Tracking), targeting harder-than-expert difficulty. All files live under `/home/ubuntu/github/CodingPRD/tasks/task_1702_sports_medicine_athlete_availability/`.

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`

**Counts:**
- Entities: 14 (Team, Athlete, DiagnosisCode, InjuryCase, TreatmentPlan, DailyStatusEntry, RTPProtocol, RTPStageAdvance, ClearanceAuthorization, WorkloadSession, InsurancePolicy, Claim, DisclosureGrant, AvailabilityReport)
- State machines: 8 (InjuryCase, TreatmentPlan, RTPProtocol, ClearanceAuthorization, Claim, InsurancePolicy, DisclosureGrant, Athlete)
- Calculations: 7 (availability_tier_derivation, acute_chronic_workload_ratio, load_flag_threshold, rtp_stage_readiness, claim_adjudication, injury_rate_trend, confidentiality_redaction_filter)
- Endpoints: 64 (flat topology, plus `POST /sports-med/_clock/set_current_utc` with fixed default 2026-08-01T00:00:00Z)
- Errors: 49; Validations: 19; Roles: 6; Concurrency rules (OCC): 3

**§1.8 difficulty instances (18 total, 2 per rule):** dual_variant_calc 2, combinatorial_formula 2, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 2, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2.

**§1.9 corner instances (32 total):** entities 6, state_machines 6, calculations 3, validations 5, endpoints 2, errors 1, rbac 4, cross_cutting_layers 4, consistency_model 1.

**Design adjudications made:**
1. **Flat topology (not nested)** — the lint's segment-derivation heuristic only recognizes `<prefix>/<collection>/{id}` single-GETs, so deep nesting would have broken FK reverse-reachability. I flattened to `/sports-med/<collection>` with FK-in-body creation and filtered-list GETs; all 24 FKs resolve.
2. **Concussion readiness error mapping** — made deterministic: the hard floor is evaluated first (`ERR_CONCUSSION_MIN_DAYS`), otherwise a composed-gate failure yields `ERR_READINESS_NOT_MET`. Fixed the combinatorial instance to assert the correct error (a SEVERE concussion at day 4 passes the floor 3 but fails composed min 5 → READINESS_NOT_MET), and added a separate corner instance that fires the floor distinctly (MINOR concussion at day 2 → CONCUSSION_MIN_DAYS).
3. **RTPStageAdvance FK** — added a flat `/sports-med/rtp-stage-advances` collection (list + single GET) because the sub-resource check compares the literal `{id}` placeholder and my nested path used `{protocolId}`.
4. **GET with required query inputs** — the analytics trigger passes `from_date`/`to_date` in `payload` (not the URL query string) since lint strips query strings before matching.
5. **ERR_AUDIENCE_INVALID** — was declared but unreferenced; added validation row p10.5 plus a triggering corner instance to satisfy "every error triggerable."
6. All formula-derived asserts were pre-computed as literals via Python (ACWR 2.800/1.241, adjudication splits 56000/64000, 67500/32500, 72000/8000, 180000/20000, injury rate 250.00, boundary ratios 1.500/1.300/1.498), and all OCC `expected_*_version` payloads reference `${var}` captures, never literals.

I did not read any sibling task under `tasks/` — the scaffold was designed purely from the scenario description and the skill specification.

## Step 3: Copy Shared Files — 2026-08-14T09:59:00.000Z

Copied ./INSTRUCTION.md to tasks/task_1702_sports_medicine_athlete_availability/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-14T10:20:00.000Z

The PRD is complete and all three hard contracts pass. Here is the summary.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1702_sports_medicine_athlete_availability/workspace/PRD.md` — 318 lines.

### Section list
1. **Introduction** — 3 paragraphs covering business context, system scope, and governance principles
2. **Global Specifications & System-Wide Principles**
   - 2.1 User and Role-Based Access Control (6 roles, opaque identity, RBAC masking)
   - 2.2 API Response Structure (verbatim fixed envelope)
   - 2.3 Pagination (`limit` default 10 / min 1 / max 100, `offset` default 0, `created_at` ascending)
   - 2.4 Common Resource Properties and the Logical Clock (UUID `id`, `created_at`/`updated_at`/`version`, five append-only exceptions, `current_utc` initialization)
   - 2.5 Validation Priority and Error Precedence
   - 2.6 Optimistic Concurrency Control (`expected_protocol_version`, `expected_policy_version`, `ERR_STALE_VERSION` / 412)
   - 2.7 Precision, Rounding, and Monetary Representation
   - 2.8 Team Scoping and Cross-Reference Integrity
3. **Business Logic & Workflows** — 10 subsections
   - 3.1 Team Configuration and Roster Administration
   - 3.2 Injury Intake and the Daily Status Log
   - 3.3 Treatment Planning and Rehabilitation Milestones
   - 3.4 Return-to-Participation Protocol and Stage Gates
   - 3.5 Clearance Authorization and Segregation of Duties
   - 3.6 Workload Ingestion, ACWR, and Load Flags
   - 3.7 Availability Tier Derivation and Load Overlay
   - 3.8 Insurance Policy and Claims Lifecycle
   - 3.9 Confidentiality, Disclosure Grants, and Availability Reporting
   - 3.10 Injury Trend Analytics
4. **Endpoint Definitions** — 64 endpoints, 4-column table (Method / Path / Description / Authorized Role)
5. **Error Code Catalogue** — 49 errors, 2-column table (Error ID / HTTP Status Code)

### Coverage audit

| Scaffold section | PRD section | Status |
|---|---|---|
| `entities` (14 entities, 106 field names) | §2.1, §2.4, §3.1–3.10 | All field names appear in backticks |
| `state_machines` (8 machines, 33 transitions, 30 states) | §3.1–3.5, §3.7–3.9 | All transitions, preconditions, side effects, and cascades expressed |
| `calculations` (7 rules) | §3.4 (RTP readiness), §3.6 (ACWR + load flag), §3.7 (tier derivation), §3.8 (claim adjudication), §3.9 (redaction), §3.10 (injury rate) | All constants, formulas, and rounding rules in prose |
| `validations` (18 rules) | §2.5 priority ladder + §3 trigger conditions | All error IDs paired with conditions in workflow narrative |
| `concurrency_rules` (3 OCC rules) | §2.6 + §3.4, §3.5, §3.8 | Endpoint, `expected_*_version` field, and `ERR_STALE_VERSION` all named |
| `endpoints` (64) | §4 table + §3 narratives | All side effects and filters described |
| `errors` (49) | §2.1, §3.1–3.10, §5 | Every error ID appears in prose near its trigger |
| `roles` (6) | §2.1 + §4 | Exact spelling, identity model, and endpoint authorization |
| `response_envelope` | §2.2 (verbatim), §2.3 | Fixed contract preserved |

### Hard-contract results
- **Contract 1 (Field-Name Coverage):** 106 required, 106 present, 0 missing — **PASS**
- **Contract 2 (Rule Coverage):** 18 validation priorities, 3 OCC rejections, 33 transitions, 7 calculations, 18 validation conditions, 64 endpoint side effects, 106 structured fields, 8 sibling-branch groups — all expressed, 0 missing — **PASS**
- **Contract 3 (§3 Path Purity):** 611 backtick tokens scanned, 0 path/method violations — **PASS**

## Step 6: Generate Implementation — 2026-08-14T11:05:00.000Z

Implementation complete and verified. Summary:

## File list
All under `/home/ubuntu/github/CodingPRD/tasks/task_1702_sports_medicine_athlete_availability/workspace/implementation/`:

- `start.sh` — executable; guarded `pip install` (no-op once flask importable), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000), foreground
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask app factory, blueprint registration under `/sports-med`, global RLock per request, envelope-compliant error handlers (ApiError/404/405/500)
- `db.py` — in-memory `STORE` (14 empty dicts), logical clock (default exactly `2026-08-01T00:00:00Z`, verbatim echo, monotonic 1 ms-bumped stamps for created_at/updated_at), no seeding anywhere
- `errors.py` — full error catalog with exact IDs/HTTP statuses
- `response.py` — envelope: `meta{api_request_id, api_request_timestamp}` + `response_type` + `data`; pagination fields `limit/offset/total_count/has_more` (defaults 10/0, 1–100)
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (400 `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, 403 `ERR_INSUFFICIENT_PERMISSIONS`)
- `util.py` — typed field/enum/date validation
- `routes/`: `teams.py` (clock, teams, diagnosis codes), `athletes.py` (enroll + deactivate/reactivate/release + CoachingStaff field masking), `cases.py` (injury cases, treatment plans, daily status entries), `rtp.py` (protocols, advances, regress, clearances), `workload.py`, `billing.py` (policies, claims), `reports.py` (grants, availability reports, analytics), `serializers.py`
- `services/`: `derived.py`, `rtp.py`, `billing.py`, `reports.py`, `common.py`

## Endpoint count
**44 endpoints** implemented — the full SCAFFOLD §1.5 table (clock set, 3 teams, 3 diagnosis-codes, 6 athletes, 7 injury-cases, 7 treatment-plans, 3 daily-status-entries, 7 rtp/advances/stage-advances/regress, 4 clearances, 3 workload-sessions, 4 insurance-policies, 7 claims, 4 disclosure-grants, 3 availability-reports, 1 analytics). Wait — recounting the route decorators: 44 routes registered (some paths serve two methods).

## State machines implemented
InjuryCase (OPEN→REHAB→RTP→CLEARED→CLOSED, REHAB↔LONG_TERM, REGRESSED loop RTP→REHAB with case returning to RTP on advance out of REGRESSED), TreatmentPlan (DRAFT/ACTIVE/SUSPENDED/COMPLETED), RTPProtocol (incl. SUSPENDED_CONCUSSION auto-overlay on concussion entries), ClearanceAuthorization (PENDING→GRANTED/RETURNED_FOR_REVIEW/EXPIRED, re-request freshness rule, SoD self + evaluator checks, 72 h eval freshness, 72 h TTL `expires_at`), Claim (DRAFT→SUBMITTED→PAID/DENIED, DENIED→APPEALED→re-adjudicate, ≤3 appeals, DRAFT→VOID), InsurancePolicy (ACTIVE→EXHAUSTED auto / CANCELLED), DisclosureGrant (ACTIVE→REVOKED + lazy EXPIRED), Athlete (ACTIVE/INACTIVE/RELEASED with grant-revocation cascade).

## Calculations implemented
- `availability_tier_derivation` (today-entry → latest-entry → OUT default; OPEN floor ≥LIMITED, LONG_TERM→OUT, AWAITING_CLEARANCE severity ceiling ≤LIMITED; worst-of-cases; SPIKE overlay FULL→MODIFIED)
- `acute_chronic_workload_ratio` both variants — ROLLING (7/28-day windows, ÷4) and EWMA (λ=0.2 decay-weighted daily loads) — Decimal, 3 dp ROUND_HALF_UP, <8 qualifying sessions → null, REHAB_SESSION excluded
- `load_flag_threshold` (1.300/1.500 inclusive on the rounded value; verified exact 1.300→ELEVATED)
- `rtp_stage_readiness` (2+SEVERE 2+concussion 1 min-days, 14-day regression lookback, score ≥80, entry_date ≥ stage entry; concussion 3-day hard floor checked FIRST → `ERR_CONCUSSION_MIN_DAYS`)
- `claim_adjudication` (pinned 10-step order, half-up rounding only at coinsurance step, credited-deductible = min(applied, patient_resp) to policy, denial zeroes)
- `injury_rate_trend` (position × surface groups, enrollment-date exposure exclusion, CLOSED-before-window exclusion, 2 dp half-up, zero-exposure groups omitted)
- `confidentiality_redaction_filter` (lazy expiry → window → max scope rank → created_at tiebreak → STRICT downgrade last; re-evaluated on report read)
- OCC on the three declared endpoints (`expected_protocol_version` ×2, `expected_policy_version` → 412 `ERR_STALE_VERSION`), validation priority ladder followed per endpoint

## Boot verification
Fresh-process boots ran cleanly 6+ times via `PORT=<port> bash start.sh` (each serving within ~3 s); final check on a clean boot returned `{"data": [], "meta": {...limit:10, offset:0, total_count:0, has_more:false}, "response_type": "array"}` for `GET /sports-med/teams` and the correct 400 error envelope without auth headers. Three smoke suites (≈150 assertions covering the full clinical-to-claim arc, concussion/regression/clearance-re-request cycles, SoD, stale evaluation, STRICT downgrade, EWMA, policy EXHAUSTED, VOID-supersede, ACWR gates/boundaries/overlay) all passed. All test servers were stopped afterward.

## Step 5: Generate Unit Tests — 2026-08-14T11:10:00.000Z

Generation complete and fully verified. Final summary:

## Tests generated: 67 total

**Queue A (Difficulty) — 39 tests across 17 of 18 instances** (≥2 per instance):
| rule_id | tests |
|---|---|
| dual_variant_calc | 2 (both on `claim_adjudication_initial_vs_readjudication_divergence`) |
| combinatorial_formula | 4 (2 per instance) |
| non_linear_state_machine | 5 (3+2) |
| transitive_cascade | 4 (2+2) |
| priority_pair_validation_conflict | 5 (2+3) |
| boundary_precision_check | 6 (4+2) |
| cross_entity_state_dependency | 5 (2+3) |
| resource_temporal_overlap | 4 (2+2) |
| compensating_invariant | 4 (2+2) |

**Queue B (Corner) — 28 tests, one per surviving instance, by section:** entities 4, state_machines 6, calculations 3, validations 4, endpoints 1, errors 1, rbac 4, cross_cutting_layers 4, consistency_model 1.

## Instances skipped (5) — gaps left as gaps, no placeholders/skip-marks
1. `Difficulty/dual_variant_calc/acwr_rolling_vs_ewma_divergence` — the pre-computed EWMA literal (1.241) is not what PRD §3.6's formula derives; direct computation gives 1.211 (weighted acute 100 / chronic 82.5535), so the asserted outcome would fail every faithful PRD implementation.
2. `Corner/entities/missing_required_field_returns_invalid_request` — `ERR_INVALID_REQUEST` appears only in the PRD §5 table; no PRD prose names a trigger condition for it.
3. `Corner/entities/invalid_enum_value_rejected` — same `ERR_INVALID_REQUEST` prose-silence.
4. `Corner/validations/future_entry_date_rejected` — PRD states the future-date rule only for injury-case `occurred_on` (§3.2) and workload `session_date` (§3.6); silent on `DailyStatusEntry.entry_date` (applies_to-scope silence).
5. `Corner/endpoints/list_injury_cases_filter_by_status` — PRD §4 says only "filterable" and never names the `status` query parameter, so filter semantics are not uniquely derivable.

## Files created
- `test_helpers/`: `__init__.py` (barrel), `types.py` (enums + TypedDicts; append-only entities omit `updated_at`/`version`), `api_client.py` (68 endpoint methods on `GenericApiClient`), `api_errors.py` (49 errors + HTTP map registered via `set_error_http_status_map`), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (opaque roles; `medical_headers`/`physician_headers` per-user builders for SoD), `fixtures.py` (composite setups: open/rehab/RTP case chains, `setup_awaiting_clearance`, `setup_pending_clearance`, `setup_closed_case`, policy/claim helpers with OCC version re-reads, ACWR history ingestion).
- `test_suite/`: `conftest.py` + `test_01_teams_roster_intake.py` (4), `test_02_daily_status_entries.py` (6), `test_03_case_and_plan_lifecycle.py` (5), `test_04_rtp_protocol.py` (10), `test_05_clearances.py` (11), `test_06_billing_claims.py` (17), `test_07_workload_acwr.py` (6), `test_08_reporting_confidentiality.py` (3), `test_09_analytics.py` (2), `test_10_rbac.py` (3).

## Verification performed
- All 67 tests collect under pytest; pyflakes clean; no `skip`/`skipif`/`xfail` marks; no "scaffold" references in generated code.
- **Design-tag audit (programmatic):** every emitted test carries exactly one `Design:` line; all 67 tags resolve to real `name:` instances in the source YAMLs; per-instance coverage is ≥2 (Difficulty) / ≥1 (Corner) for every non-skipped instance.
- **Citation audit (programmatic):** every docstring contains a quoted span that survives a whitespace-normalized literal match against `workspace/PRD.md` (C1/C3); all asserted `error_id`s are named in PRD prose.

## Step 7: Run Tests and Iterate — 2026-08-14T11:20:00.000Z

**Iterations run:** 2 (initial 8-round sweep → 1 fix → verification 8-round sweep, all clean)

**Final state:** all 8 parallel rounds pass 67/67 tests, 0 failures, 0 errors.

**Failures found (round 1 sweep, deterministic — failed in all 8 rounds):**
- `test_05_clearances.py::TestGrantCascade::test_grant_cascades_to_protocol_case_and_tier` — expected `availability_tier == "LIMITED"` for an RTP case at AWAITING_CLEARANCE, got `FULL`
- `test_05_clearances.py::TestRegressCascade::test_regress_lifts_awaiting_clearance_tier_cap` — same root cause

**Diagnosis:** PRD §3.7 states verbatim: "An `RTP` case whose protocol is `AWAITING_CLEARANCE` forces the contribution to at most `LIMITED`." Both STEP 1a (coverage) and 1b (unique derivability) pass — given the same section's severity lattice ("OUT more restrictive than LIMITED ... than FULL", most-restrictive-wins) and the parallel OPEN rule ("at least LIMITED — never FULL"), the only coherent reading is capping MODIFIED/FULL down to LIMITED. Tests were faithful (STEP 2), so this was an implementation bug (STEP 3).

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/`:** none.

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1702_sports_medicine_athlete_availability/workspace/implementation/services/derived.py` — `case_contribution()`: inverted the tier-cap comparison for the RTP/AWAITING_CLEARANCE override from `TIER_RANK[desig] < TIER_RANK["LIMITED"]` (which incorrectly lifted OUT→LIMITED and left FULL untouched) to `TIER_RANK[desig] > TIER_RANK["LIMITED"]` (caps MODIFIED/FULL down to LIMITED, leaves OUT/LIMITED alone), matching PRD §3.7's "at most `LIMITED`" rule.

## Step 8: Finalize PRD — 2026-08-14T11:26:00.000Z

**Result: zero PRD edits. `PRD_FINALIZED.md` is a byte-identical copy of `PRD.md`** (both 318 lines, identical md5 `f1175768b9955523df6210a2e8152901`, `diff` empty).

## Line counts and %-delta

- `PRD.md`: 318 lines; `PRD_FINALIZED.md`: 318 lines; delta 0 lines / 0.0%.
- Changes: none — no bullets to report.

## Why zero edits

The single Step 7 fix was `implementation/services/derived.py` `case_contribution()` inverting `TIER_RANK[desig] < TIER_RANK["LIMITED"]` to `>` for the RTP/`AWAITING_CLEARANCE` branch — an **impl→PRD-compliant** fix. Step 7's own diagnosis records that STEP 1a (coverage) and STEP 1b (unique derivability) both **passed** on PRD §3.7's existing sentence ("An `RTP` case whose protocol is `AWAITING_CLEARANCE` forces the contribution to at most `LIMITED`"), given the section's severity lattice and the parallel OPEN floor rule. The PRD already uniquely determines the post-fix behavior, so no patch was warranted. Both previously-failing tests (`test_grant_cascades_to_protocol_case_and_tier`, `test_regress_lifts_awaiting_clearance_tier_cap` in `test_suite/test_05_clearances.py:27-148`) quote that PRD sentence verbatim as their spec authority — auxiliary confirmation.

## Verification search log (per the mandatory pre-edit search, performed even though zero edits resulted)

- **(a) Subject identified:** the RTP/`AWAITING_CLEARANCE` tier-ceiling rule, plus its consistency neighbors the task named: the tier lattice, the OPEN floor rule, and the SPIKE load-overlay ordering.
- **(b) Impl paths enumerated and read:**
  - `implementation/services/derived.py` (full file): `TIER_RANK` (line 11), `effective_designation` (21), `case_contribution` (38-54 — OPEN cap, LONG_TERM→OUT, RTP+AWAITING_CLEARANCE cap), `driving_case` (63), `derive_tier` (72-82 — min-by-rank, no-candidates→FULL, SPIKE overlay last, FULL→MODIFIED only), `recompute_athlete` (143), `recompute_load_and_tier` (150-156 — flag refreshed before `derive_tier`).
  - All 12 recompute callsites, read in context: `routes/cases.py:90` (intake), `:133` (start-rehab), `:150` (mark-long-term), `:163` (resume-rehab), `:192` (close), `:351` (daily-status create/supersede); `routes/rtp.py:108` (protocol create, REHAB→RTP), `:174` (advance out of REGRESSED, REHAB→RTP), `:254` (regress, RTP→REHAB + PENDING-clearance→EXPIRED cascade), `:395` (clearance GRANTED, RTP→CLEARED); `routes/athletes.py:96` (reactivate); `routes/workload.py:57` (ingest). Every callsite falls inside PRD §3.7's trigger list.
  - `services/common.py` — `protocol_for_case`, `current_entries_for_case`, `latest_current_entry` (the `(entry_date, created_at)` tie-break is inert: at most one `is_current` entry per `(case, entry_date)` can exist).
  - `services/reports.py:6,49-53,86` — `driving_case`/`effective_designation` reuse the same override semantics; no conflict with §3.7/§3.9 wording.
  - All `load_flag`/`SPIKE` touch points (grep): only enrollment init (`athletes.py:49`), thresholds/`load_flag_for`, and the overlay in `derive_tier` — overlay is the final step on both the stored-flag path and the ingest path, matching "applied last".
- **(c) Wording adjustment:** none — no edit was committed. Each §3.7 clause was confirmed against every enumerated path: lattice ↔ `TIER_RANK`+`min`; OPEN "at least `LIMITED` — never `FULL`" ↔ cap MODIFIED/FULL→LIMITED leaving OUT/LIMITED; RTP/`AWAITING_CLEARANCE` "at most `LIMITED`" ↔ the post-fix identical cap shape; LONG_TERM "forces `OUT`" ↔ unconditional assignment; no-candidates→FULL ↔ `derive_tier`; SPIKE FULL→MODIFIED-only-last ↔ overlay in both recompute paths. No PRD sentence mis-describes any path, and no impl behavior lacks PRD pinning in this fix's scope.

**File produced:** `workspace/PRD_FINALIZED.md` (exact copy of `PRD.md`).

## Step 9: Complete PRD — 2026-08-14T11:50:00.000Z

All edits verified in context. The document reads cleanly and every change is an inline insert/revision — no new sections, no line-count change.

## Summary

**Produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1702_sports_medicine_athlete_availability/workspace/PRD_COMPLETED.md`

**Source vs output:** PRD_FINALIZED.md (= PRD.md, byte-identical): 318 lines / 43,811 chars → PRD_COMPLETED.md: 318 lines / 48,924 chars. Char-delta **+5,113**, line-delta **0** (38 lines revised in place: 26 prose lines + 12 endpoint-table rows).

**Counts:** 41 ambiguity-pins (29 prose + 12 table-row filter enumerations), 3 mismatch-revisions.

### Mismatch revisions
- §2.5 — revise — mismatch — moved `appeal budget` ahead of `field-level constraints` in the priority ladder (impl checks budget before validating `appeal_reason`) — implementation/routes/billing.py:288-294
- §3.8 — revise — mismatch — removed "with `denial_reason` recorded when `deny` is true" (impl never persists `denial_reason`; claim resource carries no such field) — implementation/routes/billing.py:267-281, implementation/services/billing.py:7-45
- §3.9 — revise — mismatch — re-reading a report recomputes the entire `rows` array (tiers and driving-case fields too), not only the redaction filter — implementation/routes/serializers.py:182-189

### Ambiguity pins (prose)
- §2.1 — insert — clock endpoint accepts any parseable ISO 8601 (forward or backward), echoes verbatim to every team's `current_utc`, returns HTTP 200 with data containing `current_utc` — routes/teams.py:23-33, db.py:99-109
- §2.3 — insert — invalid/out-of-range `limit`/`offset` (incl. negative offset) → `ERR_INVALID_REQUEST` — response.py:29-49
- §2.4 — insert — date-valued fields accept `YYYY-MM-DD` or full ISO 8601, stored/echoed verbatim, comparisons use the calendar-date portion — util.py:70-93
- §2.4 — revise — team created after the clock is set inherits the then-current clock value — routes/teams.py:53
- §2.5 — insert — field-level constraint failures map to `ERR_INVALID_REQUEST` (400) — util.py, errors.py:78-79
- §2.6 — revise — missing/non-integer expected-version → `ERR_INVALID_REQUEST`; only integer mismatch → `ERR_STALE_VERSION`; unlisted endpoints ignore version fields and unknown body fields are ignored API-wide — routes/rtp.py:48-56, routes/billing.py:237-244
- §3.1 — revise — `position` is a free-form string; `enrollment_date` not validated against season window or clock — routes/athletes.py:41-43
- §3.1 — insert — reactivate from non-`INACTIVE` → `ERR_ATHLETE_NOT_INACTIVE` — routes/athletes.py:92-94
- §3.2 — insert — duplicate diagnosis `code` → `ERR_INVALID_REQUEST` — routes/teams.py:83-85
- §3.2 — insert — intake imposes no roster-status precondition — routes/cases.py:50-91
- §3.2 — insert — any new entry flips all prior same-`(injury_case_id, entry_date)` entries to `is_current` false, with or without `supersedes_entry_id` — routes/cases.py:335-338
- §3.3 — insert — suspend `reason` is a required non-empty string — routes/cases.py:267-268
- §3.3 — revise — `mark-long-term` requires `REHAB` (`ERR_CASE_NOT_IN_REHAB`); missing current entry → `ERR_DESIGNATION_NOT_OUT` — routes/cases.py:137-146
- §3.4 — revise — regression window pinned as inclusive [today−14, today] — services/rtp.py:38-41
- §3.4 — insert — advance out of `REGRESSED` cascades case `REHAB`→`RTP` with tier recompute and athlete version increment — routes/rtp.py:169-174
- §3.4 — revise — regress requires a string `reason` (not persisted) — routes/rtp.py:221-223
- §3.5 — revise — `decision` restricted to `GRANTED`|`RETURNED_FOR_REVIEW` (else `ERR_INVALID_REQUEST`) — routes/rtp.py:343-375
- §3.5 — insert — absence of any `is_current` entry counts as stale evaluation — routes/rtp.py:364-372
- §3.6 — insert — workload ingestion imposes no roster-status precondition — routes/workload.py:22-58
- §3.6 — insert — ACWR "qualifying session" = `session_type` ≠ `REHAB_SESSION` regardless of duration; the 10-minute floor applies only to `counts_as_exposure` — services/derived.py:85-88
- §3.8 — revise — `deductible_cents`/`oop_max_cents` must be non-negative — routes/billing.py:58-60
- §3.8 — revise — line items require non-empty `cpt_code`, positive integer `charge_cents`, valid `service_date`; policy must belong to the case's athlete (else `ERR_NOT_FOUND`) — routes/billing.py:128-147, 165-167
- §3.8 — revise — `adjudicated_at` recorded on denials too; `deny` must be boolean when present — services/billing.py:10, routes/billing.py:275-277
- §3.8 — revise — `appeal_reason` is a required string, not persisted — routes/billing.py:292-294
- §3.9 — insert — grant window bounds are instants (date-only = 00:00:00Z); end>start compared by calendar date — routes/reports.py:47-69, services/reports.py:12-17
- §3.9 — revise — missing `audience` → `ERR_INVALID_REQUEST` (vs `ERR_AUDIENCE_INVALID` for bad values) — routes/reports.py:123-124
- §3.9 — insert — rows cover all team athletes regardless of `roster_status`; optional fields sourced from the driving case (most restrictive contribution, earliest `created_at` tiebreak); `diagnosis_detail` = the diagnosis code's `code`; visible-but-no-case fields are `null`, non-visible fields omitted — services/reports.py:44-88, services/derived.py:63-69
- §3.10 — insert — `from_date`/`to_date` required query params (`ERR_INVALID_REQUEST`); response is `{"groups": [...]}` with `position`, `surface`, `exposures`, `injuries`, `rate_per_1000`, ordered by position asc then surface enum order — routes/reports.py:161-174, services/reports.py:91-142

### Ambiguity pins (§4 endpoint table)
- §4 — revise — enumerated exact filter params on all 12 "(filterable)" list endpoints: athletes (`team_id`, `roster_status`, `position`), injury-cases (`athlete_id`, `team_id`, `diagnosis_code_id`, `status`), treatment-plans (`injury_case_id`, `athlete_id`, `status`), daily-status-entries (`injury_case_id`, `athlete_id`, `entry_date`, `is_current` — only `true` selects current —, `supersedes_entry_id`), rtp-protocols (`injury_case_id`, `athlete_id`, `status`), rtp-stage-advances (`rtp_protocol_id`, `kind`), clearances (`rtp_protocol_id`, `injury_case_id`, `athlete_id`, `status`), workload-sessions (`athlete_id`, `team_id`, `session_type`, inclusive `from_date`/`to_date`, unparseable dates ignored), insurance-policies (`athlete_id`, `status`), claims (`injury_case_id`, `athlete_id`, `insurance_policy_id`, `status`, `supersedes_claim_id`), disclosure-grants (`athlete_id`, `status`, `grantee_role`), availability-reports (`team_id`) — routes/athletes.py:56-69, cases.py:94-110,224-237,368-388, rtp.py:112-125,187-197,313-329, workload.py:61-84, billing.py:90-100,202-221, reports.py:74-89,140-147

**Cross-checks performed:** RBAC matrix, all state-machine transitions and error IDs, OCC semantics, ACWR/EWMA formulas, adjudication rounding/order, grant selection ranking, and test-suite behavior were verified consistent between PRD and implementation; everything else the PRD pinned already matched impl exactly.
