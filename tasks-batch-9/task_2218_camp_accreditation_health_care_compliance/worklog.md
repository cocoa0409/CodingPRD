# Worklog — task_2218_camp_accreditation_health_care_compliance

## Step 1: Create task directory — 2026-09-01T03:44:03.868Z

Created `tasks/task_2218_camp_accreditation_health_care_compliance/` and `tasks/task_2218_camp_accreditation_health_care_compliance/workspace/`.

## Step 2: Generate Scaffold — 2026-09-01T05:34:49.388Z

All three scaffold artifacts for task 2218 are complete and the linter reports `VERDICT: clean lint`.

## Files
- `/home/ubuntu/github/CodingPRD/tasks/task_2218_camp_accreditation_health_care_compliance/SCAFFOLD.yaml` (§1.0–§1.7, 164 KB)
- `/home/ubuntu/github/CodingPRD/tasks/task_2218_camp_accreditation_health_care_compliance/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8, single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_2218_camp_accreditation_health_care_compliance/SCAFFOLD_CORNER_DESIGN.yaml` (§1.9, single key `scaffold_corner_design`, 271 KB)

## §1.0–§1.7 surface
- **Profile:** `difficulty_level: expert_plus`; archetypes compliance_audit + multi_party_negotiation; layers optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers; `role_model: segregation_of_duties`; `consistency_model: immediate`.
- **Entities: 13** — Camp, StandardsSet, Standard, AccreditationCycle, StandardEvaluation, WrittenPlan, Visitor, AccreditationVisit, VisitAssignment, Deficiency, MedicationAdministrationRecord, AnnualReport, IncidentDisclosure.
- **Endpoints: 58** — 26 GETs (2 computed reads: cycle compliance-summary, camp risk-index), 31 writes, plus the logical-clock endpoint.
- **State machines: 11** — including two parallel axes on Camp (accreditation_status, state_license_status) and two independent dimensions on StandardEvaluation (self_status / visit_status); AccreditationCycle forks three ways out of VISIT_COMPLETED.
- **Calculations: 10** — standards applicability determination (4 gates, verdict frozen onto the evaluation), required_health_staffing_level (5 components + combination bump), mandatory_compliance_score (variants visit_provisional / office_final), camp_risk_index (variants pre_visit / post_visit), accreditation_decision_level, accreditation_fee_assessment (per-line round_half_up, domain surcharges, multi-year discount), deficiency_penalty_and_deadline, camp_compliance_posture, controlled_substance_ledger, visitor_travel_commitment.
- **Validations: 55** (priority-ordered) / **Error catalog: 55** ids / **Roles: 5** — CampDirector, HealthCareStaff, Visitor (all entity-backed), AccreditationOfficer, StateLicensingAgent. 3 OCC rules (`expected_camp_version` on cycle + written-plan creates, `expected_cycle_version` on visit create).

## §1.8 — 9 rule_ids × 19 instances
dual_variant_calc (2), combinatorial_formula (3), non_linear_state_machine (2), transitive_cascade (2), priority_pair_validation_conflict (2), boundary_precision_check (2), cross_entity_state_dependency (2), resource_temporal_overlap (2), compensating_invariant (2).

## §1.9 — 9 sections × 69 instances (46 with full test recipes, 23 `excluded_because` stubs)
entities 12, state_machines 15, calculations 17, validations 12, endpoints 4, errors 1, rbac 3, cross_cutting_complexity_layers 4, consistency_model 1.

## Verification
- Linter: 58 endpoints, 13 entities, 19 §1.8 + 46 §1.9 instances, **1117 calls scanned**, clean.
- All 55 error ids are reachable from a named instance (audited; zero untriggered).
- No duplicate instance names across the two design files; every `excluded_because.difficulty_instance` resolves to a real §1.8 instance name; no stub carries a `test_recipe`; no forbidden concurrency vocabulary anywhere.
- Design defects caught and fixed during generation: two unreachable errors (`ERR_CORRECTION_WINDOW_EXPIRED`, `ERR_PLAN_REVISION_LIMIT`) were made reachable by sheltering PLAN_SUBMITTED from clock escalation and adding a plan-replacement self-loop; one §1.8 assert contradicting an escalation side effect was corrected.
- The hard constraint was honoured: no sibling task directory under `tasks/` was listed, read, or grepped.

Unrelated pre-existing stray file noted, left untouched: `skills/prd-bench-scaffold-generator/SCAFFOLD_CORNER_DESIGN.yaml` belongs to task 2205 and was already untracked before this work started.

## Step 3: Copy Shared Files — 2026-09-01T05:34:49.388Z

Copied `INSTRUCTION.md` → `tasks/task_2218_camp_accreditation_health_care_compliance/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T05:50:15.338Z

PRD written to `/home/ubuntu/github/CodingPRD/tasks/task_2218_camp_accreditation_health_care_compliance/workspace/PRD.md`.

**Line count:** 458 lines. Ends at the final §5 table row — no audit footer inside the document.

**Sections (1 + 9 + 9 + 2):**
- §1 Introduction (3 paragraphs)
- §2 Global Specifications: 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim) · 2.3 Pagination and Collection Filtering · 2.4 Common Resource Properties and the Logical Clock · 2.5 Validation Precedence and Path Resolution · 2.6 Version Pinning and Optimistic Concurrency Control · 2.7 The Two Camp Status Axes and the Compliance Posture Gate · 2.8 The Freeze Cascade and Conserved Quantities · 2.9 Numeric Precision and the Camp Risk Index
- §3 Business Logic: 3.1 Registering a Camp, Sizing its Health Centre, and the State Licensing Axis · 3.2 The Standards Book · 3.3 Opening a Cycle and Freezing Applicability · 3.4 Written Plans and the Camp Self-Assessment · 3.5 Assembling and Confirming the Visiting Team · 3.6 On-Site Scoring, Finalisation and Deficiency Creation · 3.7 The Accreditation Decision and Fee Assessment · 3.8 Deficiency Correction, Escalation and the Logical Clock · 3.9 Health Centre Records, Annual Reporting and Incident Disclosure
- §4 Endpoint Definitions (58 rows, 4 columns) · §5 Error Code Catalogue (55 rows, 2 columns)

```
Field coverage check:
- entities[].fields: 148 required (127 unique), 148 present, 0 missing
- endpoints[].request_body / input: 114 required (normalized, optional markers stripped), 114 present, 0 missing
- endpoints[].query_params: all present, 0 missing
- endpoints[].path_params: 13 required, 13 present, 0 missing
- non-entity computed/control identifiers (23: compliance_component, incident_component,
  program_component, staffing_gap_penalty, license_penalty, population_multiplier,
  provisional_denominator/numerator, final_denominator/numerator, weighted_total, weighted_met,
  projected_decision_level, expected_camp_version, expected_cycle_version, decision,
  controlled_intake_units_added, to_iso8601, current_utc, escalated_deficiency_count,
  terminated_cycle_count, limit, offset): 23 present, 0 missing
Passes run: 2 (both clean)
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 55 checked, 55 expressed in prose, 0 missing (full 11-tier ladder in §2.5, with the two commonly-inverted orderings called out explicitly)
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (each names its write operation, its expected_<parent>_version field, its error_id and HTTP 412), 0 missing — framed purely as stale-version pinning, no concurrent-write language anywhere
- state_machines[].transitions: 72 checked, 72 fully expressed, 0 missing (includes both RESCINDED entries, the SCHEDULED→DRAFT and VISIT_SCHEDULED→SELF_ASSESSMENT reversions, the PLAN_SUBMITTED self-loop, VERIFIED↔REVALIDATION_REQUIRED, and ACCEPTED→REOPENED/ARCHIVED)
- calculations[]: 10 checked, 10 fully expressed, 0 missing (all constant tables enumerated; both dual-variant pairs — provisional/office-final compliance and pre-visit/post-visit risk — written out side by side; per-item rounding order pinned for the fee and for the incident component)
- validations[] conditions: 55 checked, 55 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 58 endpoints checked, all side-effect chains expressed, 0 missing (freeze cascade, finalize-scoring five-hop, deactivation three-level unwind, decision per-branch divergence)
- entities[].fields[] structured content: 127 checked, 127 reconstructible from prose (type, bounds, enum domain, default, computed-vs-input), 0 missing
- sibling-branch symmetry: 6 groups checked (4 decision levels; 4 deficiency review decisions; 3 medication classes; 2 compliance variants; 2 risk variants; 2 annual-report landings), 6 with equal prose density, 0 asymmetric
- errors: 55 catalogued, 55 HTTP codes match the scaffold, 0 mismatches
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 953 (351 unique)
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
- unbackticked path strings in §3 prose: 0
Status: PASS
```

Two under-specified scaffold points were resolved with determinate readings and stated as rules: `required_specialist_domains` derivation (aquatics/adventure program elements, and `RN_ONSITE`/`PHYSICIAN_ONSITE` requirement for health), and the missing-licence-number case on a move into `ACTIVE` (rejected under the schema tier with `ERR_INVALID_REQUEST`). The scaffold's shared use of `ERR_INCIDENT_OUTSIDE_REPORT_YEAR` for both the written-plan date-order rule and the disclosure-year rule was reproduced faithfully rather than normalised. Neither withheld design file was opened, grepped, or referenced, and no sibling task directory was read.

## Step 5: Generate Unit Tests — 2026-09-01T07:26:26.296336725Z

All work is complete. Final audit passes clean.

## Files

**Test infrastructure** — `test_helpers/` (9 files): `__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`.

**Test cases** — `test_suite/`: 31 files, **143 tests**.

| Queue | Files | Tests | Instances |
|---|---|---|---|
| A (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, §1.8) | `test_01`–`test_09` | 41 | 19 / 19 non-stub |
| B (`SCAFFOLD_CORNER_DESIGN.yaml`, §1.9) | `test_10`–`test_31` | 102 | 46 / 46 non-stub |

Queue-B section breakdown: entities 12, state_machines 13, calculations 11, validations 14, endpoints 16, errors 4, rbac 11 (`test_27`–`test_29`), cross_cutting_complexity_layers 4 (`test_30`), consistency_model 4 (`test_31`).

## Instances skipped

**None.** All 65 non-stub instances (19 + 46) passed the PRD-first two-condition filter and were translated; the 23 `excluded_because` stubs were never touched. Verified mechanically: 0 uncovered non-stub instances, 0 tests tagged at a stub.

## Audit results (all green)

- Every test has exactly one trailing `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line, resolving to a real non-stub instance in the source yaml.
- Every docstring opens with a `PRD §x.y: "…"` quote that is byte-verbatim in `workspace/PRD.md`, and every section label matches the section the quote actually lives in (two labels corrected from §3.5 to §3.6 in `test_28`, one truncated quote in `test_20` restored to the full PRD sentence).
- No `skip`/`skipif`/`xfail`, no mocking, no occurrence of the word "scaffold"; `compileall` clean; no unused imports in any test file (only the deliberate re-export surface in `test_helpers/__init__.py`).

## Design-index defects adapted (asserted outcome preserved in every case)

1. `patch_endpoints_return_the_whole_camp…` and `every_derived_field_is_readable…` move the licence `NONE → PROBATION` / `NONE → SUSPENDED`, which §3.1's eight permitted moves forbid — routed through `NONE → ACTIVE` first (version counts shift by one write, still +1 each).
2. `report_year_gates_each_disclosure…` calls the disclosure status `DISCLOSED`; the PRD/enum value is `REPORTED`.
3. `camp_and_visitor_scoped_actors…` call 2 does a cross-camp `GET /camps/{id}`, which §2.1 does not uniquely derive as `ERR_FORBIDDEN_SCOPE`; the same claim ("scope is not a write-only concern") is asserted on a cross-camp **cycle** read, which §2.1 names verbatim.
4. `the_officer_who_scheduled_the_visit…` — officer identities are opaque, so setup/confirm roles are mirrored (officer-1 builds, officer-2 confirms); the refusal is asserted against the confirming officer and the acceptance against both a third officer (`officer-3`) and the building officer, which pins the instance's distinguishing aspect that the bar is the confirm stamp alone.
5. Earlier-session carry-overs: `AQUATICS_OPEN_WATER` on a DAY camp forces `HEALTH_WELLNESS` into `required_specialist_domains`, contradicting the design's own `[AQUATICS]`/`team_size == 3` → switched to `AQUATICS_POOL`; `team_role: "SPECIALIST"` → `SPECIALIST_AQUATICS`; `ERR_VISITOR_INACTIVE` is 409, not the design's 422.

## Step 6: Generate Implementation — 2026-09-01T07:26:26.296336725Z

The implementation is complete and verified.

## Files created

`workspace/implementation/` (20 files, ~3,700 lines of Python):

- **Infrastructure**: `app.py` (app factory + `ApiError`/`HTTPException`/catch-all handlers), `start.sh` (executable, `exec python3 app.py`, `0.0.0.0:$PORT` default 10000, installs deps only if Flask is missing), `requirements.txt`
- **Core**: `errors.py` (all 55 error ids → statuses), `clock.py` (logical clock, initial `2026-08-01T00:00:00Z`, 3-digit-millisecond ISO), `db.py` (13 in-memory dicts, `common_fields`, once-per-request `touch`, deterministic `ordered` via internal `_seq`), `response.py` (envelope + pagination), `middleware.py` (RBAC/identity), `validators.py` (schema + query-param validation), `helpers.py` (13 `*_or_404` resolvers, scope checks, filter specs, `public()` projection), `domain.py` (26 KB — every calculation, cascade and conserved-quantity recompute)
- **12 blueprint modules** under `routes/`: camps, standards, cycles, evaluations, plans, visitors, visits, assignments, deficiencies, medications, reports, clock_control

## Self-check results

- **58 routes**, cross-checked programmatically against `SCAFFOLD.yaml`'s endpoint list: zero missing, zero extra (28 GETs, 29 mutating `/accreditation` routes, `POST /_clock/set_current_utc`).
- **Error catalogue**: `ERROR_STATUS` is exactly the PRD's 55 ids with identical HTTP statuses (diffed against the PRD table).
- **Entity field shapes**: for every one of the 13 SCAFFOLD entities, a live stored row's key set equals the SCAFFOLD field list plus common fields — zero missing, zero extra.
- **Four end-to-end smoke suites** all pass (`/tmp/smoke_2218.py`, `smoke2`, `smoke3`, `smoke4`), covering: full happy path to a DENIED decision with three-hop freeze cascade (VERIFIED plan → `REVALIDATION_REQUIRED`, citing evaluation → `REJECTED`, intake `SUSPENDED`); both compliance variants side by side (provisional 50.00 vs final 66.67); controlled-medication staffing/licensure/witness/stock/24 h-window gates plus idempotent void and balance restoration; team seating rules (conflict of interest is LEAD-only for home state, travel buffer, training currency, block-inside-window), withdraw/deactivate cascades unwinding seat → visit → cycle; the correction lifecycle (`ACCEPT_PLAN` → `VERIFY_CORRECTION`, `WAIVE` at zero open findings → cycle `CLOSED` + `ACCREDITED_WITH_CORRECTION → ACCREDITED` upgrade), revision-limit escalation, clock-driven escalation with penalty re-entry and `PLAN_SUBMITTED` sheltering; annual reports with late submission, `REOPENED` disclosure and the risk-index breakdown.
- **Fee rounding** verified against the PRD's own one-cent example: 5 % discount over all four surcharge domains yields `228856` (per-line-item rounding gives 64126 for the surcharge line where a single final rounding would give 64125).
- **Fresh-boot cleanliness**: launched twice via `bash start.sh` on separate ports; every collection returns `total_count: 0`, the clock reads the initial instant, no seeded rows anywhere. Storage is dicts only — a repo-wide scan found no `open(`, `sqlite`, `json.dump` or `pickle` usage. `__pycache__` directories removed so the checked-in tree is source-only.

Two notes for the caller: no `ERR_*` id exists for a handful of PRD-described rejections (disallowed licence transitions, missing licence number, duplicate `edition_code`/standard `code`, plan review from an inadmissible status, inverted travel block), so those return `ERR_INVALID_REQUEST` (400); and revalidating a plan while the camp is frozen returns `ERR_CAMP_POSTURE_FROZEN` (409). List endpoints authorize by role but do not auto-scope rows to the acting camp, since the PRD applies scope checks only to single-resource reads and writes.

## Step 7: Run Tests and Iterate — 2026-09-01T07:51:55.63548233Z

All 8 parallel rounds pass 143/143.

## Summary

**Iterations run:** 2 (each an 8-round parallel sweep, 143 tests, per-test-server isolation).

- Sweep 1: 140/143 in all 8 rounds — the same 3 failures in every round (deterministic, not flaky).
- Sweep 2 (after fixes): 143/143 in all 8 rounds.

**Tests deleted:** none. All 3 failing assertions traced to verbatim PRD sentences; two were implementation bugs and one was a test-side ambiguity that was made determinate rather than dropped.

**Fixes applied to `test_suite/`**
- `test_suite/test_10_entity_contracts.py`, `test_unresolvable_body_foreign_keys_404_ahead_of_every_business_rule` — the seat probe sent `visit_id` *and* `visitor_id` both unresolvable and demanded `ERR_VISIT_NOT_FOUND`. PRD §2.5 contains two rules that conflict on exactly that payload: "identifiers are resolved … in the order the body fields are listed below" (§3.5 lists `visit_id` first → `ERR_VISIT_NOT_FOUND`) versus "The order among resource kinds is fixed: … a visitor reached through `visitorId` or `visitor_id` yields `ERR_VISITOR_NOT_FOUND`; then a visit … yields `ERR_VISIT_NOT_FOUND`" (visitor first → `ERR_VISITOR_NOT_FOUND`). Two PRD-faithful readers diverge, so the double-unknown probe is not uniquely derivable. Rather than delete the assertion, the fixture now seats a **real** visitor and leaves only `visit_id` unresolvable — `ERR_VISIT_NOT_FOUND` is then the answer under *both* readings, and the design intent (body FKs 404 ahead of business rules) is preserved intact. No assertion weakened; still an exact `error_id` + 404 check.

**Fixes applied to `test_helpers/`:** none needed.

**Fixes applied to `implementation/`**
- `routes/deficiencies.py`, `review_deficiency` — the correction-window check was gated to `VERIFY_CORRECTION` only, so `ACCEPT_PLAN` / `REJECT_PLAN` after the due date succeeded. PRD §3.8: "A finding sitting in `PLAN_SUBMITTED` past its due date is not escalated by the clock at all — the office holds the pending plan — but a review arriving after the date is refused with `ERR_CORRECTION_WINDOW_EXPIRED`." Since `VERIFY_CORRECTION` requires `PLAN_ACCEPTED`, that sentence can only govern the two reviews admissible from `PLAN_SUBMITTED`. Check now covers `ACCEPT_PLAN`, `REJECT_PLAN`, `VERIFY_CORRECTION`; it stays in the temporal tier, so `WAIVE` from `PLAN_SUBMITTED` still reports `ERR_DEFICIENCY_INVALID_STATE` (§2.5 tier 7 outranks tier 11). `WAIVE` was deliberately left out — PRD does not state a window rule for it.
- `routes/evaluations.py`, `record_visitor_score` — the visit-state gate read `active_visit(row.cycle)`, which made `ERR_VISIT_CYCLE_MISMATCH` structurally unreachable (if the visitor holds a seat on the row's cycle's visit, the cycles match by construction), and a cross-cycle row reported `ERR_VISIT_INVALID_STATE`. PRD §3.6's last clause — "that the row belong to the same cycle as the visit on which the visitor holds their seat, or it is rejected with `ERR_VISIT_CYCLE_MISMATCH` (HTTP 422)" — plus the error's presence in the §2.5 tier-10 ladder and the §5 catalogue require the reference visit to be *the visitor's seated visit*. The handler now resolves that visit (the row's cycle visit when the visitor is seated on it, otherwise their live `IN_PROGRESS` visit), keeps §2.5 ordering (scope → visit state → locked → certification → applicability → cycle coherence), and compares `visit["cycle_id"]` to the row's cycle. This also removed the ad-hoc `seat_on_any_live_visit` bypass that had no PRD basis. `ERR_FORBIDDEN_SCOPE` for an unseated visitor and `ERR_VISIT_INVALID_STATE` for a not-yet-started visit are unchanged.

`results.*.json` and `__pycache__` artifacts were cleaned up; no seeded data, no persistence, and no new endpoints/fields were introduced.

## Step 7b: Orchestrator re-verification sweep — 2026-09-01T07:57:07.662642453Z

Re-ran the 8-round parallel sweep from the orchestrator to regenerate `workspace/implementation/results.{1..8}.json` (Step 7's subagent had deleted them on exit). All 8 rounds: 143/143 passed.

## Step 8: Finalize PRD — 2026-09-01T07:57:07.662642453Z

Done. `PRD_FINALIZED.md` written.

## Line counts
- `PRD.md`: 458 lines; `PRD_FINALIZED.md`: 458 lines — **0.00 %** line delta (4 lines revised in place, no lines added/removed).

## Changes

- **§2.5 item 4 (Existence)** — *revise* — body identifiers are resolved in the fixed resource-kind order given in the ladder, explicitly *not* in the order an endpoint's payload description names them; added the worked consequence that a seat request with both `visitor_id` and `visit_id` unresolvable fails on the visitor — `routes/assignments.py:49-50`
- **§3.8, `VERIFY_CORRECTION` bullet** — *revise* — pinned the correction-window test as guarding `ACCEPT_PLAN`, `REJECT_PLAN` and `VERIFY_CORRECTION` alike, `WAIVE` exempt, and the temporal test running after the starting-state and `WAIVE`-severity tests — `routes/deficiencies.py:96-101`
- **§3.6, "The visit-scoring dimension"** — *revise* — introduced the **reference visit** (row's cycle's non-rescinded visit when the actor is seated on it, else the actor's earliest-seated `IN_PROGRESS` visit, else fall back to the row's cycle visit), re-anchored all five gates to it in impl order (scope → visit state → locked → applicable → cycle coherence) and restated the mismatch test as `row.cycle_id` vs `reference_visit.cycle_id` — `routes/evaluations.py:100-148`
- **§2.1, `Visitor` bullet** — *revise* — the seat requirement for a visitor verdict now points at "the visit that §3.6 resolves as the reference visit" instead of asserting "the cycle's `IN_PROGRESS` visit" (which would have mis-predicted `ERR_FORBIDDEN_SCOPE` where impl returns `ERR_VISIT_CYCLE_MISMATCH`) — `routes/evaluations.py:110-126`

## Per-edit pre-edit search log

**Edit 1 — §2.5 body-FK resolution order**
- (a) Subject: order of existence resolution across body foreign keys.
- (b) Enumerated: `grep -n "_or_404" routes/*.py` (every resolution site); `helpers.py` resolvers; every multi-FK endpoint read in full — `routes/assignments.py:36-50` (visitor before visit, payload lists `visit_id` first), `routes/cycles.py:72-73` (camp then edition), `routes/evaluations.py:40-41` (path `evaluationId` then body `written_plan_id`); confirmed all remaining bodies carry a single FK (`plans.py:45`, `medications.py:59`, `reports.py:40`, `visitors.py:44`, `standards.py:98`, `visits.py:45`).
- (c) Adjustment: kept "URL path first" verbatim (only mixed path+body endpoint, self-assessment, satisfies both readings); scoped the new clause to "the endpoint's own payload description", which is true of assignments and vacuous-but-consistent for cycles (where both readings agree), rather than claiming payload order is *never* the kind order.

**Edit 2 — §3.8 correction window on officer review**
- (a) Subject: `correction_due_date` window enforcement.
- (b) Enumerated: `grep -rn "correction_due_date\|correction_deadline_at" --include=*.py` → `routes/visits.py:248` (stamping at deficiency creation), `routes/deficiencies.py:56` (filing a plan — PRD already pins), `routes/deficiencies.py:96-101` (the review site), `routes/deficiencies.py:137` and `routes/cycles.py:265-270` (`correction_deadline_at` derivation/clearing), `routes/clock_control.py:33-41` (clock escalation, `OPEN`/`PLAN_ACCEPTED` only, `PLAN_SUBMITTED` sheltered). Also re-read the §2.5 tier ordering (tier 7 `ERR_DEFICIENCY_INVALID_STATE` vs tier 11 `ERR_CORRECTION_WINDOW_EXPIRED`) against `deficiencies.py:86-101`.
- (c) Adjustment: scoped the new sentences to the *review* endpoint only, so they cannot be read as adding a window rule to clock escalation (which is status-keyed, not decision-keyed) or to `correction_deadline_at`; stated the `WAIVE` exemption positively so the pre-existing generic phrase "a review arriving after the date" can no longer be read as covering `WAIVE`.

**Edit 3 — §3.6 reference-visit resolution**
- (a) Subject: which visit the visitor-score gates read, and `ERR_VISIT_CYCLE_MISMATCH` reachability.
- (b) Enumerated: `routes/evaluations.py:97-159` in full (seat collection, two-branch resolution, `None` fallback, gate order); `domain.active_visit` / `cycle_visits` / `visitor_assignments` and `db.ordered` (`created_at`, `_seq` ascending — the "earliest-seated" wording); the other two visitor-acting endpoints `routes/visits.py:140-168` (`start_visit`) and `171-191` (`finalize_scoring`), both keyed on `lead_visitor_id` not seats; `domain.recompute_visit_scoring_counts` and the row's `visit_id` stamping; §2.5 tiers 5/7/8/10 for the gate order.
- (c) Adjustment: worded the fallback branch explicitly (`ERR_FORBIDDEN_SCOPE` is also the answer when no reference visit resolves) so the unseated-visitor and no-visit-at-all paths are not mis-described; left the certification-gate sentence and the "sets the row's `visit_id`" sentence verbatim (on success the reference visit *is* the row's cycle visit, so both stay true); avoided the phrase "in this order" so the sentence does not compete with the §2.5 ladder that actually places the certification gate between `ERR_EVALUATION_LOCKED` and `ERR_STANDARD_NOT_APPLICABLE`.

**Edit 4 — §2.1 Visitor seat requirement**
- (a) Subject: the same seat-scope requirement, restated in the RBAC section.
- (b) Enumerated: `routes/evaluations.py:110-126` (resolution + scope rejection); `routes/visits.py:147-150` and `178-181` (lead-only checks, the other half of the same bullet); `helpers.scope` / `middleware.CAMP_SCOPED_ROLES` (confirmed `Visitor` is not camp-scoped, so no second scope path exists for this write).
- (c) Adjustment: replaced "the cycle's `IN_PROGRESS` visit" with a pointer to §3.6's reference visit rather than deleting the requirement — the old phrasing would have mandated `ERR_FORBIDDEN_SCOPE` for a visitor seated on another cycle's live visit, where the implementation reaches `ERR_VISIT_CYCLE_MISMATCH`; the first clause of the bullet (lead-only for opening/closing scoring) was left untouched.

## Step 9: Complete PRD — 2026-09-01T08:06:16.566540093Z

All 30 edits landed in-paragraph; the file is still 458 lines (no new sections, no new paragraphs).

## Summary

**Source vs completed:** `PRD_FINALIZED.md` 458 lines / 90,854 chars → `PRD_COMPLETED.md` 458 lines / 96,075 chars (**+5,221 chars, ±0 lines**).

**Counts:** 26 ambiguity-pins, 4 mismatch-revisions (30 edits total).

- §2.1 — insert — ambiguity — a present-but-empty `X-User-ID`/`X-User-Role` is treated as absent (`ERR_UNAUTHENTICATED`) — middleware.py:30
- §2.3 — insert — ambiguity — `created_at` ordering ties broken by persistence order — db.py:76
- §2.3 — insert — ambiguity — bad enum/int/bool filter values are `ERR_INVALID_REQUEST`; unlisted query params ignored — validators.py:237-255, helpers.py:116-140
- §2.4 — revise — mismatch — `version` starts at 1 and advances once *per mutating request*, not once per field mutation — db.py:56-71, camps.py:88-97
- §2.4 — insert — ambiguity — the clock may be set backwards as well as forwards — clock.py:19
- §2.5 — insert — ambiguity — instants accept none-to-six fractional digits, echoed normalised to three — validators.py:11-12, clock.py:31-35
- §2.5 — insert — ambiguity — bounds for the otherwise-unspecified free-text fields (2000 / 500 / 5000 / 80) — deficiencies.py:42,74, visitors.py:67, camps.py:107
- §2.9 — revise — mismatch — risk index is *also* recomputed on decision issuance, and never on deficiency review or clock escalation; the component read derives live rather than echoing stored — cycles.py:280, deficiencies.py:129-131, camps.py:37
- §3.1 — insert — ambiguity — censuses must be integers, `distance_to_hospital_km` may be fractional — camps.py:52-54
- §3.1 — insert — ambiguity — an impermissible licence pairing (incl. a no-op) is `ERR_INVALID_REQUEST`, raised after camp existence — camps.py:111-115
- §3.2 — insert — ambiguity — duplicate `edition_code` → `ERR_INVALID_REQUEST` — standards.py:48-52
- §3.2 — insert — ambiguity — duplicate standard `code` within an edition → `ERR_INVALID_REQUEST` — standards.py:104-108
- §3.3 — insert — ambiguity — a spent `cycle_year` stays blocked even for `TERMINATED`/`CLOSED` cycles — cycles.py:89-94
- §3.3 — insert — ambiguity — `projected_decision_level` is never null, computed live from current figures and licence status — cycles.py:56
- §3.4 — revise — ambiguity — plan review: wrong-status decision → `ERR_INVALID_REQUEST`; `REJECT` stamps `reviewer_user_id`; omitted note is sticky — plans.py:108-139
- §3.4 — insert — ambiguity — omitted `written_plan_id`/`note` on a self-assessment write leave prior values in place — evaluations.py:79-82
- §3.4 — revise — ambiguity — `SUBMITTED → SUBMITTED` self-score revision is permitted — evaluations.py:83
- §3.4 — insert — ambiguity — submit-self-assessment requires `SELF_ASSESSMENT` (`ERR_CYCLE_NOT_IN_SELF_ASSESSMENT`) ahead of both gates — cycles.py:175-179
- §3.5 — insert — ambiguity — supplied `employer_camp_id` must exist (`ERR_CAMP_NOT_FOUND`) — visitors.py:43-44
- §3.5 — insert — ambiguity — opening a visit on a non-`SELF_ASSESSMENT` cycle → `ERR_CYCLE_NOT_IN_SELF_ASSESSMENT`, after the version pin — visits.py:53-56
- §3.5 — insert — ambiguity — reversed travel block → `ERR_INVALID_REQUEST` before existence resolution — assignments.py:43-47
- §3.5 — insert — ambiguity — seat release: wrong visit status or non-`ASSIGNED` seat → `ERR_VISIT_INVALID_STATE`, visit tested first — assignments.py:132-138
- §3.5 — insert — ambiguity — the `self_assessment_submitted_at` gate is last and yields `ERR_SELF_ASSESSMENT_INCOMPLETE` — visits.py:125-129
- §3.6 — insert — ambiguity — one shared `note` field across both scoring dimensions, overwritten only when supplied — evaluations.py:152-153
- §3.6 — insert — ambiguity — finalisation refreshes the cycle's `open_deficiency_count` — visits.py:261
- §3.7 — insert — ambiguity — the visit precondition fails with `ERR_VISIT_INVALID_STATE`; a cycle with no visit clears segregation vacuously — cycles.py:214-228
- §3.7 — insert — ambiguity — the `TERMINATED` branch leaves stored `open_deficiency_count` at 0 — cycles.py:255-259
- §3.8 — revise — mismatch — all four deficiency decisions stamp `reviewer_user_id`; omitted `reviewer_note` is sticky — deficiencies.py:103-105
- §3.9 — revise — mismatch — the controlled dosing window counts only records at the same camp — medications.py:96-107
- §3.9 — insert — ambiguity — re-voiding a `VOIDED` record is a no-op 200, no error and no version bump — medications.py:149-157

Nothing under `implementation/` was modified; `results.*.json` untouched.
