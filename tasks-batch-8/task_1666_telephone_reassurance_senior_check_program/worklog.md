# Worklog — task_1666_telephone_reassurance_senior_check_program

## Step 1: Create Task Directory — 2026-08-14T06:03:00.000Z

Task directory `tasks/task_1666_telephone_reassurance_senior_check_program/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE per orchestrator instructions; no index scan performed, no other task directory touched.

User directive: difficulty target is **harder than expert level** — conveyed to scaffold generator.

## Step 2: Generate Scaffold — 2026-08-14T07:32:00.000Z

Scaffold generation complete for task_1666 (Telephone Reassurance & Senior Check-In Program). All three artifacts were written and the official linter is clean.

### Files written (all three, verified)
- `SCAFFOLD.yaml` — §1.0–§1.7 only (confirmed: no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

### Counts
- **Entities: 16** (Program, Participant, EmergencyContact, WaitlistEntry, VolunteerCaller, AvailabilityWindow, TrainingRecord, ConfidentialityAgreement, CallSchedule, CallAssignment, CallLog, EscalationCase, WelfareCheckRequest, ServiceReferral, SatisfactionSurvey, OutcomeReport) — flat topology with FK web incl. a self-referential `EscalationCase.supersedes_escalation_id`
- **State machines: 12** (72 transitions; cyclic Participant/VolunteerCaller/WaitlistEntry/ServiceReferral loops + branching EscalationCase) plus **3 OCC concurrency rules** (escalation-create on Participant, promotion-run on Program, config-PATCH on Program — each passes the serial-observability filter)
- **Calculations: 12** (4 with dual variants: intake-vs-rolling acuity, windowed-vs-streak reliability, per-survey-then-aggregate satisfaction rounding, provisional-vs-final report rates; combinatorial modes a/b/c all present)
- **Validations: 13** priority levels (auth → ownership → existence → OCC → state → intake posture → safety → temporal → referential → constraint → cooling-off → SoD)
- **Endpoints: 85**, **Errors: 32** (all triggerable — verified programmatically), **Roles: 5** (4 opaque + `VolunteerCaller` entity-backed; segregation-of-duties on escalation resolve)
- **§1.8: 24 instances, all 24 non-stub** (rules 1–9 with 3/3/3/2/3/3/3/2/2 instances; every numeric assert pre-computed by executing the formulas — e.g. acuity 55 vs rolling 68.5, reliability 90.0 vs 85.0, completion 80.0 vs 66.7, satisfaction index 2.65 vs rejected pooled 2.64, priority scores 185/132/74, load boundary 225/270)
- **§1.9: 77 instances** (74 active with full replayed chains, 3 `excluded_because` stubs citing real §1.8 instance names)

### Verification
- `scaffold_lint.py` final verdict (verbatim): **"VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5."** — 1390 calls scanned, 0 violations
- Additional audits passed: instance-name uniqueness across both files (101 unique), all `grounds:` refs resolve into §1.1–§1.6, no forbidden race vocabulary, enum closure, trigger↔side-effect matching, state-machine triggers map to §1.5 endpoints
- Fixes applied during QA: capacity rule rewritten to a pinned `gross_free`/`reserved` evaluation order (the original formulation deadlocked CRITICAL admissions); the reschedule "OCC rule" was reclassified out of `concurrency_rules` (it fails §1.2.1's serial-observability filter) and replaced with a true-race config-PATCH rule; lint discovered the `{id}` placeholder naming requirement for sub-resource FK checks, so all single-id path templates were normalized
- No sibling task directories were read at any point — the design is derived solely from the scenario text and the skill specification

## Step 3: Copy Shared Files — 2026-08-14T07:35:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1666_telephone_reassurance_senior_check_program/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-14T07:58:00.000Z

All audits pass. The PRD is complete at `workspace/PRD.md` — **366 lines**.

### Section list
- §1 Introduction (2 paragraphs)
- §2 Global Specifications: 2.1 RBAC (5 roles + identity semantics), 2.2 API Response Structure (verbatim block), 2.3 Pagination, 2.4 The Logical Clock, 2.5 Common Resource Properties, 2.6 Request Validation Order, 2.7 Optimistic Concurrency Control, 2.8 Program Capacity Accounting, 2.9 Precision and Rounding, 2.10 Resource Existence and Path Validation
- §3 Business Logic (9 subsections): Program Setup/Intake Posture; Participant Intake/Acuity/Admission; Waitlist Offers/Promotion Runs; Volunteer Roster (Training/Confidentiality/Reliability); Schedules/Availability/Assignment Booking; Participation Interruptions (Suspend/Hold/Disenroll/Reapply); Call Outcomes/No-Answer Protocol; Welfare Checks/Resolution Governance/Service Referrals; Closeout/Surveys/Outcome Reporting
- §4 Endpoint Definitions — 4-column table, 85 rows matching all 85 scaffold endpoints
- §5 Error Code Catalogue — 2-column table, all 32 errors

### Entity coverage check
All 16 entities rendered (Program, Participant, EmergencyContact, WaitlistEntry, VolunteerCaller, AvailabilityWindow, TrainingRecord, ConfidentialityAgreement, CallSchedule, CallAssignment, CallLog, EscalationCase, WelfareCheckRequest, ServiceReferral, SatisfactionSurvey, OutcomeReport).

### Zero-Silence Rule audit (scaffold §1.1–§1.7 all rendered in prose)
- Field coverage (Contract 1): entities[].fields 117/117 present; endpoints[].input 80/80 present; path params 1/1; errors 32/32; state values 47/47; all enum values present — **PASS**
- Rule coverage (Contract 2): 13 validation priorities expressed as explicit ordered evaluation (§2.6) with approve-internal ordering (safety before capacity) in §3.2; 3 OCC rules with endpoint + `expected_*_version` field + `ERR_STALE_VERSION`/412 each (§2.7); all state-machine transitions across 12 machines plus EmergencyContact/TrainingRecord status rules; all 12 calculations in precise reconstructible prose; every error ID matchable to its trigger in §2/§3; sibling branches rendered with equal density — **PASS**
- §3 Path Purity (Contract 3): 815 backticked tokens scanned in §3; 0 path tokens, 0 bare HTTP methods, 0 method+path combos — **PASS**
- No fuzzy/approximating words anywhere; no pseudocode operators in prose.
- The withheld files (SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml) were never opened; no sibling task directories read.

## Step 6: Generate Implementation — 2026-08-14T09:02:00.000Z

The implementation is complete and verified.

### File list — `workspace/implementation/`
- `start.sh` (executable; guarded `pip install`, `exec python3 app.py`, binds `0.0.0.0:$PORT` default 10000)
- `requirements.txt` (flask>=3.0,<4)
- `app.py` — Flask app factory, blueprint registration, envelope-consistent error handlers (ApiError, 404, 405, 500)
- `db.py` — in-memory store (16 dicts) + logical clock defaulting to `2026-08-01T00:00:00Z`; **no seeding of any kind**
- `errors.py` — all 32 error IDs with exact HTTP statuses
- `envelope.py` — `meta`/`response_type`/`data` envelope, `req_*` IDs, 3-fractional-digit timestamps, pagination fields `limit/offset/total_count/has_more`
- `auth.py` — `X-User-ID`/`X-User-Role` auth, 5-role authorization decorator, body parsing
- `validate.py` — payload DSL (required/unknown/enum/range/HH:MM/date/month checks → `ERR_INVALID_REQUEST`), pagination parsing
- `calc.py` — all calculation modules
- `cascade.py` — state-machine side effects and cascades
- `serialize.py` — per-entity serializers with computed fields
- `routes_programs.py`, `routes_participants.py`, `routes_volunteers.py`, `routes_assignments.py`, `routes_escalations.py`, `routes_referrals.py`, `routes_reports.py`

### Endpoints: 85
Every row of the scaffold endpoint table (clock, programs incl. promotion-runs/daily-closeout/outcome-reports, participants + lifecycle, emergency contacts, waitlist, schedules, volunteers + lifecycle, availability windows, training records, confidentiality agreements, assignments, call logs, escalations, welfare checks, referrals, surveys, reports).

### State machines: 13
Participant (incl. capacity branch to ENROLLED/WAITLISTED, WELFARE_HOLD entry/release, cooling-off reapply), WaitlistEntry (offers, MAX_DECLINES/MAX_EXPIRES), VolunteerCaller (certify/reactivate/lapse/separate), CallAssignment (incl. RESCHEDULED supersede), CallSchedule, EscalationCase (retry ladder, supersede, SoD-gated resolve with stage-specific guards), WelfareCheckRequest (disposition cascades incl. superseded-case completion resolving the new case), ServiceReferral (rework loop), SatisfactionSurvey, ConfidentialityAgreement (supersede/revoke/expire), Program intake_posture, OutcomeReport, plus the simple EmergencyContact status model.

### Calculation modules: 12
Intake acuity (capped 100, tier bands 29/59/84), rolling acuity (0.7/0.3 blend, ROUND_HALF_UP 1dp via Decimal), effective tier, effective_capacity (reserve = min(max_reserve_slots, critical_waiting)), waitlist_promotion (pinned 8-step order, 95% pressure bump affecting ranking only, tie-breaks never by id), volunteer reliability (28-day window, min-10 history, trailing-EXPIRED streak penalty, tier caps), weekly load (inclusive bound), buffer-inclusive closed-interval conflict (09:45 touch conflicts, 09:46 doesn't), volunteer selector (8-clause eligibility, least-loaded ranking), satisfaction index (pinned per-survey-round-then-aggregate — verified [5,4,3,4,5]+[1,1,1,1,1] → 4.29/2.65), referral SLA (strictly-greater overdue), required-contact-frequency coverage, outcome report provisional/final variants.

### Boot smoke test: PASS
`bash start.sh` boots cleanly from a fresh process, answers within ~2s, empty store, correct clock default. Four scenario suites (~190 assertions covering intake/capacity/waitlist/promotion OCC, volunteer lifecycle, lapse cascades, conflict/load/cap rules, no-answer escalation ladder, welfare-check dispositions, SoD, referral SLA boundary, survey/report math, pagination, RBAC, ownership, 400/401/403/404/409/412/422 error shapes) all pass — including repeated fresh reboots proving per-test-server isolation readiness.

## Step 5: Generate Unit Tests — 2026-08-14T09:10:00.000Z

All verification passes are green. The generation is complete.

### test_helpers/ (9 files)
- `types.py` — 16 entity TypedDicts + 25 enums (all entities carry full common fields)
- `api_client.py` — `ApiClient(GenericApiClient)` with 85 endpoint methods (one per PRD §4 endpoint)
- `api_errors.py` — `ApiErrorId` (32 errors) + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity structural assertions + `assert_capacity_invariants`
- `factories.py` — 13 payload factories (input fields only)
- `constants.py` — domain thresholds (tier bands, SLA hours, reliability constants, protocol defaults, 2026-08 calendar anchors)
- `test_users.py` — opaque-role shared headers + `make_volunteer_headers(volunteer["id"])` for the entity-backed VolunteerCaller role
- `fixtures.py` — composite setup: `create_program`, `enroll_participant` (auto-adds a 24h-capable contact when the intake formula predicts HIGH/CRITICAL), `waitlist_applicant`, `create_certified_volunteer`, `create_assignment`, `log_call`, `open_escalation` (OCC-anchored), `run_promotion`, `daily_closeout`, `setup_calling_environment`, etc.
- `__init__.py` — barrel export

### test_suite/ (conftest.py + 10 files, 123 tests)
| File | Tests |
|---|---|
| test_01_program_envelope_pagination.py | 6 |
| test_02_participant_intake_acuity.py | 14 |
| test_03_waitlist_capacity_promotion.py | 16 |
| test_04_volunteer_roster.py | 13 |
| test_05_schedules_booking_gates.py | 14 |
| test_06_assignment_conflicts_and_load.py | 17 |
| test_07_call_logs_and_streaks.py | 13 |
| test_08_escalations_welfare.py | 10 |
| test_09_referrals_surveys.py | 11 |
| test_10_reports_closeout_rbac_occ.py | 9 |

### Design-index coverage
- **Queue A (difficulty): 24/24 instances translated, 2 tests each (48 tests). 0 skipped.**
- **Queue B (corner): 74/74 non-stub instances translated (75 tests — the bronze-floor instance got 2). 0 skipped.** The 3 `excluded_because` stubs (cascading_side_effects_end_to_end, rate_threshold_boundaries, dual_variant_layer_coverage) were not translated; all three cross-references resolve to real queue-A instances.
- No instance failed the PRD-first filter: this PRD pins everything the indices assert (13-step validation order in §2.6, all formulas/thresholds verbatim in §3, OCC rules in §2.7).

### Judgment calls made (PRD adjudication, no weakening of pinned claims)
- `safety_certification_beats_temporal_window`: the PRD pins step-8-beats-step-9 but lists the two step-8 errors without pinning intra-step order when a volunteer fails both safety clauses, so the two tests assert the winner is one of {ERR_VOLUNTEER_NOT_CERTIFIED, ERR_CONFIDENTIALITY_NOT_CURRENT} via `validate_error_is_one_of` and explicitly that no step-9 error wins (error-precedence silence pattern).
- Weekly-load field reads (`current_week_minutes`): the PRD defines the field over the clock's current ISO week, so tests reading it set the clock into the target week first (e.g. 2026-08-03) — preserving the design's expected values (225/45/90) with PRD-consistent semantics. In `suspend_cancels_future_assignments_and_reconciles_load` the load assertion is 45 (the COMPLETED in-week row still counts per the PRD formula) rather than the design's "drops to 0", which contradicted the PRD.
- Timestamp equality asserted exactly only where the PRD pins format + value (`created_at` 3dp + clock default); computed instants (`sla_due_at`, `offer_expires_at`, `opened_at`, `waitlist_entered_at`) assert the exact instant via prefix match (rendering format not PRD-pinned for those fields).

### Verification performed
- 123/123 tests collect under `pytest --collect-only`; all modules import cleanly with `PYTHONPATH=.` and a dummy `API_BASE_URL`
- AST audit: every test docstring ends with exactly one `Design:` line resolving to a real instance; 98 distinct tags = 24 + 74, zero shortfalls
- Citation audit: all 210 `PRD §` quoted sentences survive whitespace-normalized literal match against PRD.md
- No `skip`/`skipif`/`xfail` markers; no "scaffold" references in generated code; pyflakes clean

## Step 7: Test/Fix Iteration Loop — 2026-08-14T09:35:00Z

### Iteration 1 (8-round parallel sweep): 118/123 in every round — 5 deterministic failures

Union of failures (identical across all 8 rounds):
1. `test_03::test_critical_aps_alone_applicant_wins_the_offer` — `offers_created` 2 != 1
2. `test_03::test_earlier_entrants_with_lower_scores_stay_waiting` — PB was OFFERED, expected WAITING
3. `test_05::test_coverage_deficient_tracks_required_frequency` — approve response showed coverage_deficient False, test expected True
4. `test_07::test_intake_score_static_and_rolling_blend_computed` — setup aborted with ERR_WEEKLY_LOAD_EXCEEDED
5. `test_07::test_effective_tier_takes_more_severe_of_the_two` — same setup failure

### Diagnoses (all three are unique-derivability collapses — test artifact repairs, zero implementation changes)

- **Promotion budget semantics (failures 1-2).** PRD §3.3: "A `CRITICAL`-tier entry is offered while gross free capacity remaining is at least one, each such offer decrementing it; a non-critical entry is offered while the non-critical budget remaining is at least one, each such offer decrementing that budget." The sentence never states whether a CRITICAL offer also decrements the non-critical budget. With gross_free=1, reserve=0 and a top-ranked CRITICAL entrant, the literal two-counter reading offers 2 entries while the shared-pool reading offers 1 — two PRD-faithful implementations diverge, so the scenario's offer-count assertion was not uniquely derivable. Repair (1c scenario repair, no assertion weakened): the ranking showcase now uses three non-CRITICAL entrants (HIGH/APS/alone/10-day = 155 > HIGH/HOSPITAL_DISCHARGE/11-day = 132 > MODERATE/SELF/12-day = 74) so the single non-critical budget slot gates everyone identically under both readings; ranking-beats-FIFO remains operative (FIFO would offer the earliest entrant PC). Test renamed to `test_highest_scored_late_entrant_wins_the_offer`; all assertions remain exact.
- **coverage_deficient recompute triggers (failure 3).** PRD §3.2 pins the flag false at creation and §3.5 enumerates the recompute triggers (schedule mutations, cancellation cascades, suspension/resumption, hold release, closeout); neither enrollment nor bare assignment creation is named, so the flag's value on the approve response / right after assignment creation is not uniquely determined. Repair: every flag read now follows a PRD-named schedule mutation (create, pause, resume); the clearing clause is verified after pause+resume with the future assignment in place. All assertions remain exact.
- **Weekly-load week reference (failures 4-5).** PRD §3.5 defines the field `current_week_minutes` over the clock's current ISO week, and the admission rule names that field; whether a future-dated booking is charged to the clock week or to the week of its `scheduled_date` is not pinned. The implementation charges the booking week (defensible); the setup booked 7 same-week slots against the default 240-minute cap. Repair: the setup's volunteer now carries the PRD-permitted maximum `max_weekly_minutes` 600, so the 8 bookings (7 + 1 auto retry; 8 x 45 = 360) pass under both readings. The asserted acuity math is untouched.

### Iteration 2 (8-round parallel sweep): 123/123 in all 8 rounds — CLEAN

No tests deleted. No implementation changes. Files touched: `test_suite/test_03_waitlist_capacity_promotion.py`, `test_suite/test_05_schedules_booking_gates.py`, `test_suite/test_07_call_logs_and_streaks.py`.

## Step 7: Run Tests and Iterate — 2026-08-14T09:45:00.000Z

Clean 8-round sweep achieved. Final summary:

**Iterations run: 2** (iteration 1: 5 deterministic failures × 8 rounds; iteration 2: all 8 rounds 123/123 clean)

**Tests deleted: none.** All five failures were unique-derivability collapses repairable within the test artifact (STEP 1c partial-coverage repair — scenarios adjusted so every assertion traces to verbatim PRD prose under every PRD-faithful reading; no assertion was weakened, no exact `error_id`/value check downgraded).

**Fixes applied to `test_suite/`** (all three are test-side; `test_helpers/` needed no changes):

1. `test_suite/test_03_waitlist_capacity_promotion.py` — `TestWaitlistPriorityMultifactorRanking`: PRD §3.3 pins which counter each offer family decrements ("each such offer decrementing it / that budget") but never states whether a CRITICAL offer also decrements the non-critical budget; with a CRITICAL entrant, gross_free=1, reserve=0, the two-counter reading offers 2 entries vs the shared-pool reading's 1 (the implementation implements the former, defensibly). Repaired the scenario to three non-CRITICAL entrants (HIGH/APS/alone/10-day = 155 > HIGH/HOSPITAL_DISCHARGE/11-day = 132 > MODERATE/SELF/12-day = 74) so the single budget slot gates all entrants identically under both readings; ranking-beats-FIFO stays operative. Renamed `test_critical_aps_alone_applicant_wins_the_offer` → `test_highest_scored_late_entrant_wins_the_offer`; all assertions (offers_created==1, offered ids, exact score, WAITING states) remain exact.

2. `test_suite/test_05_schedules_booking_gates.py` — `test_coverage_deficient_tracks_required_frequency`: PRD §3.2 pins the flag false at creation and §3.5 enumerates recompute triggers (schedule mutations, cancellation cascades, suspension/resumption, closeout); enrollment and bare assignment creation are not named, so the flag's value on the approve response / immediately after assignment creation is not uniquely determined. Repaired so every flag read follows a PRD-named schedule mutation (create → "planned 1 < 3" True; two more creates → "3 ≥ 3 but no future assignments" True; pause+resume with a future SCHEDULED assignment in place → False).

3. `test_suite/test_07_call_logs_and_streaks.py` — `_setup_and_run_closeout`: PRD §3.5 defines `current_week_minutes` over the clock's current ISO week and names that field in the admission rule, without pinning whether a future-dated booking is charged to the clock week or the booking's week; the implementation charges the booking week, so 7 same-week 45-minute bookings hit the default 240 cap. Setup now gives the volunteer the PRD-permitted `max_weekly_minutes` maximum of 600 (8 × 45 = 360 passes under both readings). The asserted rolling-acuity math (55 static vs 68.5 blend, MODERATE vs HIGH) is untouched.

**Fixes applied to `implementation/`: none** — the implementation was PRD-faithful under defensible readings in all three cases; the benchmark-fairness defects were in the test scenarios.

**Feedback notes for generators** (unique-derivability misses): (a) unit-test-generator should not pin promotion-run offer counts when a CRITICAL entrant coexists with non-critical entrants unless the PRD states cross-family budget decrementing; (b) derived-flag values should only be asserted at PRD-named recompute triggers; (c) load-cap setups must respect both plausible week-reference readings or use headroom that satisfies both.

## Step 8: Finalize PRD — 2026-08-14T10:00:00.000Z

`PRD_FINALIZED.md` written at `workspace/PRD_FINALIZED.md` with exactly 4 lines revised inline, all traced to the three `<step_7_diff>` test-suite fixes (no implementation fixes existed to mirror, no tests were deleted).

**Line counts / delta:** PRD.md 365 lines, PRD_FINALIZED.md 365 lines — 0.0% delta (all edits are inline sentence insertions/revisions within existing paragraphs; no new sections).

**Changes (one bullet each):**
- §3.2 — insert — after the WAITLISTED branch sentence, pinned that approval recomputes `coverage_deficient` in neither branch (flag keeps its last-held value, false for a first-time applicant) and that offer-acceptance enrollment likewise does not recompute it — impl `routes_participants.py:159-200` (approve, no `recompute_coverage` call in either branch) and `routes_participants.py:387-406` (accept_entry, no recompute).
- §3.3 — revise — promotion-run budget walk: added that the gross-free remainder and the non-critical budget are tracked independently (a CRITICAL offer does not decrement the budget; a non-critical offer does not decrement the gross-free remainder) — impl `cascade.py:286-296` (`gf_rem`/`nc_rem` decremented separately per tier).
- §3.5 — revise — created-assignment sentence: assignment creation now also recomputes the participant's `coverage_deficient` — impl `cascade.py:30-31` (`insert_assignment`, the sole assignment-insert funnel, calls `calc.recompute_coverage`).
- §3.5 — revise — weekly-load admission rule: the sum is taken over the ISO week containing the new assignment's `scheduled_date` (the booking's own week), not the clock's current week; the `current_week_minutes` field definition (clock week) is untouched — impl `calc.py:235-238` (`load_ok` uses `iso_week_key(date)`).
- §3.5 — revise — selector ranking: least-loaded ranking uses the same booking-week minutes sum instead of the clock-week `current_week_minutes` field — impl `calc.py:270-274` (`selector` ranks by `weekly_minutes(v, iso_week_key(date))`).

**Per-edit pre-edit search log:**
1. §3.3 budget independence — (a) subject: which counter each offer family decrements in the promotion walk. (b) enumerated: `cascade.py:260-310` (`promotion_run`, only walk); grep `"OFFERED"` across all impl files confirmed `cascade.py:298` is the sole offer-issuing write; `calc.py:71-93` (`critical_waiting_count`/`capacity_numbers`/`admit_ok`) — point-in-time checks used by approve (`routes_participants.py:177`) and accept (`routes_participants.py:397`), no counters decremented, already correctly described by PRD. (c) wording kept local to "the ranked list ... walked under budget" so the single-applicant rules are untouched; no claim made about `gross_free_after` (PRD never defines its formula; impl `cascade.py:309` computes `gross_free - len(offered)`).
2. §3.2 enrollment no-recompute — (a) subject: `coverage_deficient` value on admission responses. (b) enumerated: all 12 `recompute_coverage` callsites (cascade.py:31,43,110,150,247,330; routes_participants.py:229,244,491,510,522,534), the direct set in `regenerate_assignments` (cascade.py:138-139), creation-time pin (routes_participants.py:99), non-recompute at approve/accept/deny/reapply (routes_participants.py:159-200, 387-406, 203-213, 266-284), serialize exposure (serialize.py:62). (c) chose "keeps the value it last held, false for a first-time applicant" rather than "stays false" because a reapplied-then-approved participant can carry a non-false flag (reapply doesn't reset it); scoped to "approval ... in either branch" plus offer-acceptance so §3.6 resume/release transitions to ENROLLED (which do recompute) are not swept in.
3. §3.5 creation-recompute — (a) subject: whether bare assignment creation recomputes the flag. (b) enumerated: grep `store.assignments[` confirmed `cascade.py:30` is the only insert (direct create routes_assignments.py:131, reschedule-new :182, regeneration cascade.py:137, escalation-retry cascade.py:238 all funnel through it, each recomputing); cancellation paths already PRD-named. (c) used the general phrase "A created assignment ... are recomputed" so all funnel users (including reschedule and system-driven inserts) are covered without enumeration.
4. §3.5 booking-week load gate — (a) subject: which ISO week the admission-rule sum charges. (b) enumerated: `calc.weekly_minutes` (calc.py:140-152), `current_week_minutes` clock-week field (calc.py:155-156, serialized at serialize.py:112 — left untouched), `load_ok` (calc.py:235-238) called by `check_assignment_fitness` for named-volunteer create and reschedule (routes_assignments.py:66,171) and by `selector` (calc.py:263); system-driven booking via selector (cascade.py:133,236). (c) worded as "the same per-assignment sum as `current_week_minutes`, but taken over the booking's own week" so the field definition sentence (clock week) stays verbatim and consistent with the serialized field.
5. §3.5 selector ranking week — (a) subject: which week's minutes the least-loaded ranking reads. (b) enumerated: `calc.py:270-274` (`wk = iso_week_key(date)` — booking week); same callers as edit 4. (c) re-pointed the ranking phrase at "the booking-week minutes sum of the load rule above" — required by the no-new-mismatch rule, since leaving `current_week_minutes` here while pinning the gate to the booking week would have made two adjacent booking-flow sentences use the same field name for different weeks.

## Step 9: Complete PRD — 2026-08-14T10:20:00.000Z

All 25 changed lines are in-place paragraph revisions — no new sections, no structural changes.

**Files:** Source `PRD_FINALIZED.md` — 365 lines, 73,212 chars → `PRD_COMPLETED.md` — 365 lines, 76,895 chars (line delta 0, char delta **+3,667**; 25 lines revised inline).

**Counts:** 18 ambiguity-pins, 7 mismatch-revisions.

### Ambiguity-pins (PRD silent → pinned to impl)
- §2.3 — insert — ambiguity — pinned limit/offset clamping (limit<1→1, >100→100, offset<0→0; non-integer → ERR_INVALID_REQUEST), `has_more = (offset + returned) < total_count`, `created_at` ties fall back to insertion order, boolean filters accept `true`/`false` case-insensitive — validate.py:105-134, envelope.py:32, validate.py:137-138
- §2.6 — insert — ambiguity — blank/whitespace-only strings in required name/phone/policy-version fields are ERR_INVALID_REQUEST — validate.py:29-30
- §2.8 — insert — ambiguity — `max_reserve_slots` defaults to min(5, total_capacity); values above capacity rejected with ERR_INVALID_REQUEST — routes_programs.py:50-54, 111-114
- §3.1 — insert — ambiguity — mirrored the min(5, capacity) reserve default; all numeric knobs other than `no_answer_threshold` must be non-negative (ERR_INVALID_REQUEST) — routes_programs.py:40-54
- §3.1 — insert — ambiguity — single operative program: non-program-scoped workflows resolve "the program" to the earliest-created record and fail ERR_NOT_FOUND when none exists — calc.py:54-57, routes_participants.py:63-67
- §3.1 — insert — ambiguity — pausing a non-OPEN / resuming a non-PAUSED program fails ERR_INVALID_STATE — routes_programs.py:126-127, 137-138
- §3.2 — insert — ambiguity — deactivation allowed from ACTIVE or UNREACHABLE; already-REMOVED → ERR_INVALID_STATE — routes_participants.py:340-346
- §3.3 — insert — ambiguity — promotion run returns HTTP 201 with `offered_entry_ids` in ranked order and `gross_free_after` = gross free capacity minus offers created — routes_programs.py:153, cascade.py:305-310
- §3.4 — insert — ambiguity — `languages` defaults to English when omitted *or empty* — routes_volunteers.py:48-52
- §3.5 — insert — ambiguity — `effective_to` earlier than `effective_from` → ERR_INVALID_REQUEST — routes_volunteers.py:192-193
- §3.5 — insert — ambiguity — pinned `scheduled_date` (YYYY-MM-DD) and `window_start`/`window_end` (HH:MM 24h) formats, and the named-volunteer fitness-check evaluation order (certification → confidentiality → schedule → availability → language → conflict → load → cap) — routes_assignments.py:46-117
- §3.5 — insert — ambiguity — reschedule keeps the original's volunteer/`source`/`escalation_id`, excludes the original from its own conflict check, and does not re-check participant enrollment — routes_assignments.py:164-184
- §3.5 — insert — ambiguity — requesting `source` `ESCALATION_RETRY` → ERR_INVALID_REQUEST — routes_assignments.py:105-106
- §3.6 — insert — ambiguity — regenerated resumption window is schedule start +30 min, end capped at 23:59 — cascade.py:132
- §3.7 — insert — ambiguity — retry assignment's 30-minute window end capped at 23:59 — cascade.py:234-235
- §3.7 — insert — ambiguity — retry-success auto-resolution applies only while the case is still at STEP_1_RETRY — cascade.py:222-226
- §3.7 — insert — ambiguity — advancing at STEP_3_WELFARE → ERR_INVALID_STATE; contact attempts valid only at STEP_2_CONTACT (else ERR_INVALID_STATE) — routes_escalations.py:95-96, 117-118
- §3.8 — insert — ambiguity — new welfare check carries `disposition` `NONE` until completed — cascade.py:92
- §3.8 — insert — ambiguity — stage-dependent resolution matrix (RESOLVED_OK only STEP_1; RESOLVED_CONTACT_CONFIRMED STEP_1/STEP_2; CLOSED_FALSE_ALARM any stage; unavailable → ERR_INVALID_STATE) — routes_escalations.py:131-153
- §3.8 — insert — ambiguity — ASSIST_NEEDED auto-referral uses service type HOME_HEALTH (sla_due_at = +24h) — routes_escalations.py:242-253
- §3.8 — insert — ambiguity — referral decline `reason` is optional (decline_reason null when omitted) — routes_referrals.py:121-125
- §3.9 — insert — ambiguity — survey return valid only while ISSUED (else ERR_INVALID_STATE); finalizing a non-PROVISIONAL report → ERR_INVALID_STATE — routes_participants.py:598-599, routes_reports.py:34-35
- §3.9 — insert — ambiguity — `calls_completed` counts assignments whose `scheduled_date` is in the period with status COMPLETED — calc.py:401-402

### Mismatch-revisions (PRD contradicted impl → revised to impl)
- §2.8 — revise — mismatch — program `version` does NOT increment on `waiting_count`-only movements (waitlist branch of approval, decline, withdraw); pinned exact increment set: config updates, posture transitions, promotion runs, closeouts, and `occupied_slots` movements — routes_participants.py:182-199, 409-439 vs 182, 259, 405
- §3.3 — revise — mismatch — while WAITING, `priority_score_at_offer` is not nulled; it stays null only until the first offer and thereafter retains the most recent offer's score — routes_participants.py:415-417, cascade.py:339-341
- §3.3 — revise — mismatch — decline clears only `offered_at`/`offer_expires_at` (not "the offer fields" broadly) — routes_participants.py:415-417
- §3.3 — revise — mismatch — closeout offer-lapse requeue likewise clears only `offered_at`/`offer_expires_at` — cascade.py:339-341
- §3.5 — revise — mismatch — the "operations on schedules… all demand ENROLLED" generalization narrowed: only schedule creation, assignment creation, and survey issuance check ENROLLED; pause/resume/archive do not — routes_participants.py:475 vs 502-535
- §3.5 — revise — mismatch — language mismatch raises ERR_NO_ELIGIBLE_VOLUNTEER for explicitly named volunteers too, not "only through the selector" — routes_assignments.py:60-61
- §4 (table) — revise — mismatch — suspend cancels all SCHEDULED assignments (not only future-dated ones); table cell de-"future"d — routes_participants.py:226-228

Notable confirmations requiring no change: the full 13-step validation order, capacity/reserve math, promotion scoring and tie-breaks, reliability windowing/streak math, buffer-inclusive conflict rule (09:45 example verified against calc.py:189-201), closeout's five returned id lists, report provisional/final denominator split, and the 2.65 satisfaction-index rounding example all match the implementation exactly.
