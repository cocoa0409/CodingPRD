# Worklog — task_1376_building_envelope_consulting_testing

## Step 1: Create Task Directory — 2026-08-13T01:50:00.000Z

Task directory `tasks/task_1376_building_envelope_consulting_testing/` and its `workspace/` subdirectory were pre-created and pre-assigned by the invoking command; Step 1 treated as DONE (no index scan, no other task_* writes).

## Step 2: Generate Scaffold — 2026-08-13T02:12:00.000Z

All three files are written, parse cleanly, and pass the linter with a clean verdict.

**Files written:**
- `tasks/task_1376_building_envelope_consulting_testing/SCAFFOLD.yaml` (1930 lines)
- `tasks/task_1376_building_envelope_consulting_testing/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1195 lines)
- `tasks/task_1376_building_envelope_consulting_testing/SCAFFOLD_CORNER_DESIGN.yaml` (1645 lines)

**Counts:**
- Entities: 13 (Engagement, Assembly, DesignReview, ChamberSlot, MockUp, FieldTest, Survey, Anomaly, RemediationPlan, WarrantyClaim, LitigationHold, MaintenanceVisit, Invoice)
- State machines: 12 (one per entity except Engagement also carries posture derivation; includes cyclic DesignReview revision loop, MockUp FAILED→REMEDIATED→TESTING cycle, parallel dimensions on FieldTest, WarrantyClaim DENIED→ESCALATED→DENIED cycle)
- Calculations: 9 (design_review_fee, mockup_testing_fee, field_test_result_calc, remediation_cost_estimate, engagement_fee_accrual, risk_score_update, posture_derivation, warranty_recovery_share, invoice_total_calc)
- Endpoints: 92 (77 business + flat FK reverse-reachability GETs + `/_clock/set_current_utc`)
- Errors: 40, all referenced
- §1.8 non-stub instances: 18 (2 per each of the 9 rules)
- §1.9 non-stub instances: 38 across all nine claim-guide sections
- Lint: `VERDICT: clean lint` (498 calls scanned, 0 violations)

**Notable design decisions (harder-than-expert calibration):**
1. **Posture-driven gating** as primary archetype: `Engagement.posture` (OPEN/RESTRICTED/FROZEN) is derived from litigation hold + risk bands + anomaly states, and gates operations at three distinct strengths (FROZEN blocks ops, OPEN-only for approve/issue).
2. **Dual-variant calculations on two domains**: remediation ESTIMATE (contingency, no mobilization) vs ACTUAL (mobilization, no contingency) with a negative reconciliation delta; engagement fee accrual PROVISIONAL (nets recoveries, per-event floor 0) vs FINAL (chronological replay, positives only) — pinned literals 380000 vs 6980000 for an identical event stream.
3. **Combinatorial formulas in two modes**: tiered/branched `design_review_fee` (mode a, fee 812000 precomputed) and nested-rounding `mockup_testing_fee` (mode b, per-day rounding pinned; 407406 vs rejected 407405).
4. **Two OCC concurrency rules** on Engagement.version (plan create + issue), with stale-version retry recipes using `${var}` captures throughout.
5. **Precedence ambiguity**: priority conflict instances pit state-vs-safety (FROZEN beats duty-segregation) and state-vs-temporal on the same escalate endpoint.
6. **Interval semantics contrast**: half-open chamber slots (adjacent allowed) vs closed+buffered maintenance windows (touching conflicts), each with boundary tests.
7. **Segregation of duties**: field-test certifier ≠ performer; design-review approver ≠ the round's comment issuer once revision_round ≥ 1.
8. All formula-derived assertions were pre-computed with Python (round-half-up semantics) and pinned as literals; default clock `2026-08-01T00:00:00Z` declared on the clock endpoint.

Orchestrator verification: all three YAMLs parse; `SCAFFOLD.yaml` contains neither `scaffold_difficulty_design` nor `scaffold_corner_design` key (isolation holds).

## Step 3: Copy Shared Files — 2026-08-13T02:24:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1376_building_envelope_consulting_testing/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-13T02:43:59.000Z

**Output:** `tasks/task_1376_building_envelope_consulting_testing/workspace/PRD.md` — **387 lines**

**Section list:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications — 2.1 RBAC (headers, 5 roles, per-role opaque-identity prose), 2.2 API Response Structure (emitted byte-identical to the fixed verbatim block), 2.3 Pagination, 2.4 The Logical Clock (startup default `2026-08-01T00:00:00Z`, `to_iso8601`/`current_utc`), 2.5 Engagement Lifecycle, Derived Posture, and Operational Gating (full posture-derivation order; 7 FROZEN-blocked operations enumerated; 2 OPEN-required operations), 2.6 The Engagement Risk Score, 2.7 Fee Recognition, Headroom, and the Fee Cap (PROVISIONAL vs FINAL accrual), 2.8 Monetary Precision and Rounding, 2.9 Optimistic Concurrency Control (both OCC-guarded writes named with paths, `expected_engagement_version`, `ERR_STALE_ENGAGEMENT_VERSION`/412), 2.10 Common Resource Properties and Nested Retrieval (LitigationHold/Invoice reduced-property exception stated), 2.11 Validation Order (all 13 priority tiers in prose)
- §3 Business Logic — 9 domain-derived subsections (engagement setup/assemblies, design review cycle, mock-ups/chamber time, field testing/diagnosis, surveys, anomaly triage, remediation plans, warranty recovery, litigation holds/maintenance/invoicing/close-out)
- §4 Endpoint Definitions — 4-column table, all 92 scaffold endpoints present
- §5 Error Code Catalogue — 2-column table, all 40 scaffold error IDs present

**Zero-Silence Rule audit (all three hard contracts PASS):**
- **Contract 1 (Field-Name Coverage):** 87 required identifiers (all entity fields, request-body keys, query params, path params, OCC/pagination fields) — 87 present in backticks, 0 missing (pass 2, after repairing `claim_status`/`hold_status`/`visit_status`/`invoice_status` found missing in pass 1). All 74 enum/state values and all 40 error IDs present.
- **Contract 2 (Rule Coverage):** validation priority cascade expressed as an explicit 13-tier order with a worked consequence example; both OCC rules expressed (endpoint + `expected_engagement_version` + error ID + 412, no race-framing); all 45 unique state-transition pairs expressed (4 literal-match flags manually verified as covered via equivalent phrasing — manufacturer-decide branches, DENIED↔ESCALATED cycle, auto slot consumption); all 9 calculations rendered with every constant embedded (fee tiers 250000/30000/20000/40000, 10% revision surcharge, 5% specimen surcharge with per-day rounding pinned, 75 Pa reference with equality-passes boundary, severity cost table, 20% contingency vs 125000/section mobilization, chronological FINAL replay excluding recoveries, risk deltas/clamps, posture bands 40/70, recovery waterfall, 2000000-cent volume tier); all side-effect cascades stated (auto-anomaly text, supersede reversal, remediation recovery cascade, invoice recompute, version increments).
- **Contract 3 (§3 Path Purity):** 529 backtick tokens scanned in §3 — 0 paths, 0 bare HTTP methods, 0 method+path tokens. All endpoints referenced via state-transition framing or role+verb.

## Step 5: Generate Unit Tests — 2026-08-13T03:19:20.000Z

**Test counts**
- Queue A (Difficulty): 34 tests covering 17 of 18 instances (≥2 tests each)
- Queue B (Corner): 38 tests covering all 38 non-stub instances (≥1 each; the index contains no `excluded_because:` stubs)
- Total: 72 tests, all collected cleanly by pytest; every docstring ends with exactly one verbatim `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` tag resolving to a real instance; all 121 quoted PRD citations verified verbatim against PRD.md by literal grep (whitespace-normalized).

**Skipped instances (1)**
- `Difficulty/resource_temporal_overlap/maintenance_visit_closed_interval_with_buffer` — fails unique derivability. Its pinned asserts (a visit starting at `end+buffer` of the *existing* visit is rejected) assume the existing visit's `buffer_days` expands its occupancy, but PRD §3.9 expands only "the new visit's closed window, expanded by `buffer_days` days on both sides" — a PRD-faithful reader implementing new-visit-only expansion would accept the pinned trigger, so the asserted outcome is not uniquely derived. No test emitted.

**Notable adjudication**
- `Difficulty/dual_variant_calc/engagement_provisional_vs_final_fee_accrual`: the recipe files the warranty claim after plan completion, but completion flips the anomaly VERIFIED → REMEDIATED and PRD §3.8 requires the claimed anomaly to be VERIFIED at filing. The fixture reorders (claim filed/acknowledged/accepted while VERIFIED, resolved after completion), preserving every pinned assertion (provisional 380000, final 6980000).

**test_helpers/ file list**
- `__init__.py` — barrel export (framework generics + PRD-specific)
- `types.py` — 12 entity TypedDicts + 18 enums (LitigationHold/Invoice carry the reduced id+created_at set per PRD §2.10)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (incl. flat alias/reverse-reachability GETs) + `api_client` singleton
- `api_errors.py` — `ApiErrorId` (40 errors) + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` (reduced-field variant for hold/invoice) + `assert_engagement_invariants`
- `factories.py` — 13 payload factories, optional fields omitted unless supplied
- `constants.py` — risk bands, severity deltas, fee schedule, thresholds from PRD
- `test_users.py` — `TEST_USERS` shared headers for the five opaque roles + `make_*_headers` builders for identity-pinning (segregation-of-duties)
- `fixtures.py` — tiered composite helpers: active engagement, approved assembly, completed survey, verified anomaly, OCC-aware `create_plan`/`issue_plan` (live version read), `setup_issued_plan`, `setup_mock_up_testing`, `setup_field_test_recorded`, diagnosis drive, claim lifecycle

**test_suite/ file list**
- `conftest.py` — session `api` fixture, per-test connection-pool reset, five role-header fixtures
- `test_01_engagement_lifecycle.py` (6 B)
- `test_02_design_reviews.py` (4 A + 3 B)
- `test_03_mockups_and_chamber_slots.py` (8 A + 2 B)
- `test_04_field_tests.py` (6 A + 3 B)
- `test_05_surveys_and_anomalies.py` (6 B)
- `test_06_remediation_plans.py` (6 A + 4 B)
- `test_07_warranty_claims.py` (4 A + 3 B)
- `test_08_litigation_holds_and_posture.py` (4 A + 1 B)
- `test_09_maintenance_visits.py` (1 B)
- `test_10_invoices_and_closeout.py` (2 A + 5 B)
- `test_11_security_and_envelope.py` (3 B)

## Step 6: Generate Implementation — 2026-08-13T03:19:20.000Z

All checks pass. The implementation is complete and verified end-to-end against a live server across four test suites (roughly 120 assertions covering every workflow family).

**File list — `workspace/implementation/`**

| File | Purpose |
|---|---|
| `start.sh` | Executable launcher; guards `pip install` behind `python3 -c "import flask"`, then `exec python3 app.py` (foreground, `$PORT` default 10000, binds `0.0.0.0`) |
| `requirements.txt` | `flask>=3.0,<4.0` |
| `app.py` | Flask assembly, error handlers (ApiError, 404/405, catch-all), `app.run` bootstrap |
| `db.py` | In-memory `STORE` dicts (verified 0 entries at import — no seeding), logical clock defaulting to `2026-08-01T00:00:00Z` |
| `errors.py` | Full 40-entry error catalog with exact IDs and HTTP statuses |
| `response.py` | Envelope: `meta.api_request_id` (`req_…`), `api_request_timestamp` (3 fractional digits), `response_type`, `data`; pagination fields inside `meta` |
| `middleware.py` | Tier-1 header check (`X-User-ID`/`X-User-Role`), tier-2 role gate; five exact role names |
| `validators.py` | Body parsing with `parse_float=Decimal` (exact leakage arithmetic), int/num/enum/date/list validators, pagination bounds (limit 1–100) |
| `services.py` | All 8 calculations, posture derivation, risk clamping, fee-event log, per-entity serializers |
| `routes.py` / `routes2.py` / `routes3.py` | All endpoints (blueprint shared across modules) |

**Endpoint count: 92** — all 80 from the scaffold endpoint table (14 flat alias/reverse-reachability routes included: 6 flat GETs, 7 flat child lists, plus global `GET /remediation-plans` with `supersedes_plan_id` filter). Verified live: full design-review cycle with segregation, mock-up fail/remediate/retest with per-day rounding, field-test FAIL cascade (auto-anomaly + risk −25), posture gating (OPEN/RESTRICTED/FROZEN), plan OCC + supersede reversal + completion cascade, warranty escalation window + recovery waterfall, litigation hold freeze/thaw, visit buffer overlap, invoice volume tier, FINAL accrual at close-out, and all validation-order examples from PRD §2.11 (posture-before-segregation, fiscal-before-OCC).

**Design decisions where the PRD left a choice open**

1. **Derived-vs-stored computed fields** — `posture`, `fee_headroom_cents`, `invoiced_cents`, and `Survey.anomaly_count` are computed on read (pure functions of current state); `recognized_fees_cents` is stored as the provisional accumulator since the FINAL variant replaces it. Observationally identical to event-driven recomputation.
2. **`updated_at` on Engagement** — bumped on every engagement mutation (fee accruals, risk changes, flag flips) per PRD §2.10 "updated on every mutation", but `version` increments only on the seven transitions where the scaffold/PRD explicitly say so (activate, begin-close-out, close, plan create, plan issue, hold apply, hold release).
3. **Body-FK references to nonexistent resources** (e.g., `assembly_id` in a review create) return `ERR_NOT_FOUND` — the catalog's path-validation language was the closest anchor; `supersedes_plan_id` follows the PRD's explicit "anything else" → `ERR_SUPERSEDES_NOT_ISSUED`.
4. **FINAL accrual reading** — implemented the scaffold formula literally: sum of *positive* fee deltas only (supersede reversals and negative completion deltas excluded, warranty recoveries excluded, no floor). The PRD's "diverge whenever a warranty claim has resolved" example passes either way; verified the exact replay sum (2050000 vs provisional 1375000) in the e2e suite.
5. **Invalid pagination params** (`limit=0`, non-integer) → `ERR_INVALID_REQUEST` 400 rather than clamping; PRD §2.3 "accepts a minimum of 1 and a maximum of 100".
6. **Missing `decision` payload** on manufacturer-decide → `ERR_INVALID_REQUEST` (tier-4 required field); present-but-invalid value → `ERR_CLAIM_NOT_ACTIONABLE` per PRD §3.8 "any other decision value".
7. **Lifecycle gate applied literally to all child mutations** (PRD §2.5 general rule): invoice `mark-paid`/`void` and claim `resolve` are blocked outside `IN_PROGRESS`, so tests must settle invoices/claims before close-out — consistent with the close-out/close guard design.

## Step 7: Run Tests and Iterate — 2026-08-13T03:38:10.000Z

All 8 parallel rounds pass 72/72 (verified by orchestrator: results.1–8.json each show passed 72/72, failed 0).

**Iterations run: 2** (sweep 1: 2 distinct failures in the union; fixes applied; sweep 2: 72/72 passed in all 8 rounds, 0 failed, 0 errors)

**Tests deleted:** none.

**Fixes applied to `test_suite/`:**
- `test_suite/test_05_surveys_and_anomalies.py` — `TestRiskScoreAndPostureDerivation::test_rate_threshold_posture_band_crossing` (failed all 8 rounds with `assert 'RESTRICTED' == 'OPEN'`). STEP 1: the asserted rule is verbatim in PRD §2.5 ("Otherwise, if the `risk_score` is below 70, or if any anomaly of the engagement is in `OPEN` status, the posture is `RESTRICTED`") and uniquely derivable. STEP 2 verdict: TEST WAS WRONG — the setup created 5 MEDIUM anomalies but verified only 4 before asserting `posture == "OPEN"` at risk 70, leaving one anomaly OPEN, which per the cited PRD sentence forces RESTRICTED. Fixed the setup: create 4 MEDIUM anomalies upfront (verify HIGH + 4 MEDIUMs → risk exactly 70 with zero OPEN anomalies → OPEN), then create the 5th MEDIUM and verify it to cross the band (65 → RESTRICTED). All pinned values and assertions preserved; `verify` is not posture-gated per §2.5.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:**
- `workspace/implementation/app.py` — server bootstrap. `test_invoice_issue_then_mark_paid_updates_invoiced_cents` errored in 7/8 rounds at setup with "API server could not be restarted" (passed round 3, proving the test and logic were sound). Root cause reproduced locally: the runner's per-test restart does `kill -9` on the listening PID then spawns the new server immediately; the killed process's listen socket briefly outlives it, so the fresh server hits `EADDRINUSE` on bind (5/30 repro rate), and werkzeug's `app.run`/`make_server` *exit the process* (`sys.exit(1)`) on bind failure — the runner's 15s poll then finds nothing. Fixed by probing the port with a raw-socket bind retry loop (60 × 0.25s, inside the harness window) before calling `make_server(...).serve_forever()`. Verified 0/60 respawn failures after the fix. Pure startup robustness — no PRD-visible behavior added or changed, no PRD-required check weakened.

## Step 8: Finalize PRD — 2026-08-13T03:41:10.000Z

`/home/ubuntu/github/CodingPRD/tasks/task_1376_building_envelope_consulting_testing/workspace/PRD_FINALIZED.md` produced.

**Line counts:** PRD.md = 387 lines; PRD_FINALIZED.md = 387 lines; %-delta = 0% (byte-identical copy, zero edits).

**Changes:** none — both `<step_7_diff>` items resolved to "no PRD edit warranted":

- **§2.5 (posture band rule) — no edit —** the test_suite fix was a pure fixture bug ("TEST WAS WRONG" verdict). PRD §2.5 already uniquely pins the rule verbatim ("if the `risk_score` is below 70, or if any anomaly of the engagement is in `OPEN` status, the posture is `RESTRICTED`"), and the implementation matches it exactly — `derive_posture` at `workspace/implementation/services.py:98-110` with thresholds `RISK_FREEZE_THRESHOLD = 40` / `RISK_RESTRICT_THRESHOLD = 70` at services.py:20-21. No PRD silence, no mismatch.
- **Server bootstrap (app.py) — no edit —** the implementation fix is confined to the `if __name__ == "__main__":` block (app.py:44-73): a raw-socket EADDRINUSE retry probe before `make_server(...).serve_forever()`. Step 7 itself records "no PRD-visible behavior added or changed". The PRD's domain is API behavior; the process-startup contract (PORT, 0.0.0.0, foreground) lives in INSTRUCTION.md, not PRD.md. Adding prose would invent a requirement and risk a new mismatch.

**Per-edit pre-edit search log (candidate edits considered and rejected)**

**Candidate 1 — posture band crossing at risk 70**
- (a) Subject: posture derivation at the 70/40 risk boundaries and the OPEN-anomaly restriction rule.
- (b) Paths enumerated: `derive_posture` (services.py:98-110); threshold constants (services.py:13-21); every caller via grep of `derive_posture` (services.py:291 engagement serialization, plus re-derivation after risk/posture-affecting events); the fixed test (test_suite/test_05_surveys_and_anomalies.py:194-235); PRD §2.5 (PRD.md:92, 94) and §2.6 (PRD.md:98-100). All agree: `risk_score < 70` or any `OPEN` anomaly → `RESTRICTED`; 70 itself with no OPEN anomalies → `OPEN`.
- (c) No wording drafted — PRD already determines the behavior uniquely; the Step 7 failure was a fixture bug (a 5th MEDIUM anomaly left OPEN), not a PRD gap. Edit rejected.

**Candidate 2 — server port-bind retry**
- (a) Subject: HTTP server process startup / port binding.
- (b) Paths enumerated: grep for `make_server|serve_forever|PORT|EADDRINUSE` across `implementation/` — the sole bind site is app.py:44-73; `start.sh` (execs `python3 app.py`, conditional pip install); INSTRUCTION.md startup contract; PRD §2.4 (the only startup-adjacent PRD statement — the logical clock's initial reading `2026-08-01T00:00:00Z` — which the fix does not touch).
- (c) No wording drafted — the fix is harness-race robustness with zero API-observable behavior; a fresh implementer produces a behaviorally equivalent API with or without it. Any PRD sentence about socket binding would invent scope the PRD deliberately leaves to INSTRUCTION.md. Edit rejected.

**Bottom line:** PRD.md already uniquely determines every behavior Step 7 exercised; PRD_FINALIZED.md is a verbatim copy, which is the correct minimal patch.

## Step 9: Complete PRD — 2026-08-13T03:50:13.000Z

`PRD_COMPLETED.md` was created from `PRD_FINALIZED.md` and patched in 11 places after an exhaustive walk of `implementation/` (app.py, routes.py, routes2.py, routes3.py, services.py, validators.py, middleware.py, response.py, db.py).

**Source vs output**: PRD_FINALIZED.md 387 lines / 64,224 chars (wc: 64,471 bytes) → PRD_COMPLETED.md 387 lines / 66,329 chars (wc: 66,599 bytes); char-delta **+2,105**, 12 lines touched, no sections added.

**Counts**: 10 ambiguity-pins, 1 mismatch-revision.

**Changes**:
- §2.3 — insert — ambiguity — invalid `limit`/`offset` (non-integer, limit outside 1–100, negative offset) pinned to `ERR_INVALID_REQUEST` (400) — implementation/validators.py:155-175
- §2.3 — insert — ambiguity — list ordering tie-break pinned: same-timestamp resources ordered by creation sequence, earliest first — implementation/routes.py:107
- §2.3 — insert — ambiguity — `has_more` semantics pinned: true iff offset + returned page size < total_count — implementation/routes.py:116
- §2.9 — insert — ambiguity — Engagement `version` increments only at activation, plan create/issue, hold apply/release, begin-close-out, close; risk/fee/posture/plan-completion/invoice-status changes bump only `updated_at` — implementation/services.py:78-87, routes.py:185/230/254, routes3.py:149/212/438/487 vs 682/700/718
- §2.10 — insert — ambiguity — body-carried resource references (`assembly_id`, `chamber_slot_id`, anomaly parent, `anomaly_id`, `anomaly_ids` entries) resolve against the path engagement after the lifecycle gate, unresolvable → `ERR_NOT_FOUND` — implementation/routes.py:336, routes2.py:174-175/351/528/651-654, routes3.py:116/282
- §2.11 tier 4 — insert — ambiguity — body-shape tier also covers non-object/invalid JSON bodies and strict `YYYY-MM-DD` calendar-date fields — implementation/validators.py:14-28, 128-137
- §3.2 — insert — ambiguity — `review_fee_cents` stays null until APPROVED/REJECTED — implementation/routes.py:346
- §3.3 — insert — ambiguity — mock-up created with `testing_fee_cents` unset (as well as `air_leakage_lps_m2`) — implementation/routes2.py:183-184
- §3.4 — insert — ambiguity — field test's `result`, `measured_leakage_lps_m2`, `performed_by`, `certified_by` all unset at scheduling — implementation/routes2.py:360-362
- §3.6 — insert — ambiguity — anomaly list with both `field_test_id` and `survey_id` filters ANDs them — implementation/routes2.py:677-682
- §3.7 — revise — **mismatch** — "stale version rejected before anything else about the plan is considered" contradicted §2.11 tiering and impl; revised so OCC runs at the final tier after the supersedes-target rule (invalid `supersedes_plan_id` + stale version → `ERR_SUPERSEDES_NOT_ISSUED`) — implementation/routes3.py:118-130
- §3.8 — revise — ambiguity — missing/non-string `decision` → `ERR_INVALID_REQUEST` (body-shape tier), while a wrong string value or wrong state → `ERR_CLAIM_NOT_ACTIONABLE` — implementation/routes3.py:362-374

Everything else in the implementation (all 80+ endpoints, posture derivation order, risk deltas and clamping, both fee-accrual variants, the fiscal gate, all calculation formulas with pinned rounding steps, overlap/window rules, segregation-of-duties checks, validation-tier ordering, error catalogue, serializers, and the reduced property sets for LitigationHold/Invoice) was verified to already match the PRD uniquely, so no further edits were made.
