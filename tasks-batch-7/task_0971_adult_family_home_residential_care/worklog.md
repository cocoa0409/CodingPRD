# Worklog — task_0971_adult_family_home_residential_care

## Step 1: Create task directory — 2026-08-10T00:00:00.000Z

Task directory `tasks/task_0971_adult_family_home_residential_care/` and its `workspace/` subdirectory were pre-assigned and already exist; Step 1 treated as done per headless-run instructions (no auto-index scan run).

## Step 2 (resume note): Scaffold recovery — 2026-08-10T03:30:00.000Z

Resumed after SIGKILLed headless run. Found on disk: `SCAFFOLD.yaml` (2053 lines) and `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1500 lines); `SCAFFOLD_CORNER_DESIGN.yaml` missing. The original Step-2 subagent's summary was lost with the kill. Recovery actions: (1) repaired 66 unquoted `?`-suffixed plain scalars (e.g. `timezone?`) in flow sequences of `SCAFFOLD.yaml` that broke PyYAML parsing — quoted in place, no semantic change; (2) validated both files parse cleanly — SCAFFOLD.yaml: 16 entities, 68 endpoints, 23 errors, 3 roles, 10 state machines, 9 calculations, 22 validations, 3 concurrency rules, no `scaffold_difficulty_design`/`scaffold_corner_design` keys; SCAFFOLD_DIFFICULTY_DESIGN.yaml: single top-level key `scaffold_difficulty_design`, 9 rules / 18 instances, intact tail. Kept both files; regenerated only the missing corner-design file (see next entry).

## Step 2: Generate Scaffold — 2026-08-10T04:05:00.000Z

Step 2 complete. SCAFFOLD_CORNER_DESIGN.yaml generated at `/home/ubuntu/github/CodingPRD/tasks/task_0971_adult_family_home_residential_care/SCAFFOLD_CORNER_DESIGN.yaml` (~194KB). SCAFFOLD.yaml and SCAFFOLD_DIFFICULTY_DESIGN.yaml untouched.

**§1.9 sections populated: 9 of 9** (entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_layers, consistency_model)

**Instance counts per section (fresh with test_recipe / excluded_because stubs):**
- entities: 9 / 0
- state_machines: 17 / 4
- calculations: 5 / 4
- validations: 3 / 2
- endpoints: 3 / 0
- errors: 12 / 8
- rbac: 6 / 0
- cross_cutting_layers: 8 / 0 (3 OCC stale-version, 2 derived-field, 1 cascade, 1 rate-threshold, 1 scheduled-action)
- consistency_model: 1 / 0

**Total: 82 instances** (64 with full structured test_recipe, 18 stubs citing §1.8 instances). Together with §1.8's 18, the union has 100 uniquely-named instances.

**Reference integrity — confirmed by script:** every `grounds:` entry resolves to a declared element in SCAFFOLD.yaml (9 calculations, 16 entities + fields, 10 state machines + FROM_to_TO transitions, validations priorities 1–22, all 23 error ids, 3 concurrency rule ids, 3 roles, response_envelope keys). Every `excluded_because.difficulty_instance` cites an existing §1.8 instance name; stubs carry no test_recipe. Every `${var}` is bound by an earlier `captures:` in its own instance; all OCC `expected_*_version` payloads use `${var}` form. All 23 error ids are now triggerable (12 fresh triggers + 8 §1.8 stubs + ERR_NOT_FOUND/ERR_INVALID_REQUEST/ERR_UNAUTHENTICATED/ERR_STALE_VERSION covered across entities/validations/cross-cutting sections). File parses with `yaml.safe_load`, single top-level key `scaffold_corner_design`.

**Orchestrator follow-up on the subagent's lint flag:** the 11 pre-existing `(f) FK_REVERSE_UNREACHABLE` violations inside SCAFFOLD.yaml were fixed additively in §1.5 before Step 4 (so the PRD covers them): added `assessment_id?` to `GET /api/admissions`; added `caregiver_id?` to `GET /api/medication-logs` and `GET /api/adl-logs`; added single-resource GETs `GET /api/medication-logs/{id}`, `GET /api/adl-logs/{id}`, `GET /api/shifts/{id}`, `GET /api/payments/{id}`, `GET /api/discharge-records/{id}` (roles matching their list counterparts). Endpoints 68 -> 73. `scaffold_lint.py` re-run after the fix: **VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5** (73 endpoints, 16 entities, 18 §1.8 + 64 §1.9 instances, 970 calls scanned).

## Step 3: Copy shared files — 2026-08-10T04:06:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_0971_adult_family_home_residential_care/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-10T07:05:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_0971_adult_family_home_residential_care/workspace/PRD.md` (348 lines, ends at §5 Error Code Catalogue — verified complete, not truncated; §2.2 confirmed byte-identical to `section-2.2-response-structure.md`). The two withheld difficulty/corner design files were never opened; no sibling task directories were touched.

**Sections produced:** §1 Introduction (2 paragraphs, business-context angle); §2.1 RBAC + identity semantics, §2.2 verbatim envelope, §2.3 Pagination, §2.4 Logical Clock, §2.5 Common Resource Properties (incl. the four append-only exceptions), §2.6 Home-Local Time & Half-Open Intervals, §2.7 OCC, §2.8 Money/Rounding, §2.9 Validation Pipeline (all 22 checks in priority order), §2.10 Nested Retrieval, §2.11 Derived Counters; §3.1–3.8 (home lifecycle, assessment/care plan, admission pipeline, daily care logs, staffing, incidents/compliance, rate schedules/invoicing, issuing/settlement/discharge); §4 endpoint table (73 rows, 4 columns); §5 error catalogue (23 rows, 2 columns).

**Coverage-audit summary (all three hard contracts PASS):**

```
Field coverage check (Contract 1):
- entities[].fields + endpoint input/query/path identifiers: 85 required, 85 present, 0 missing
- Status: PASS

Rule coverage check (Contract 2):
- validations[] with priority: 22 checked, 22 expressed in §2.9 ordered pipeline + relative-order prose for shared endpoints, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_bed/caregiver/resident_version + ERR_STALE_VERSION/412 all named), 0 missing
- state_machines[].transitions: 39 checked (10 machines), 39 fully expressed with from/to states, preconditions paired to error ids, and side effects, 0 missing
- calculations[]: 9 checked (provisional/final invoice windows, medicaid_acuity_rate, late_fee, staffing_ratio, med_admin_window, caregiver_overlap_check, discharge_refund, report_deadline_check), 9 fully expressed in precise reconstructible prose with constants embedded (1500¢/hr, 9000¢ cap, ÷7 proration truncated then round-half-up; 5% fee clamped 2500–1500¢; 1:4/1:2/1:3 ratios; 60-min windows; 16h/1-min rolling cap; 24h00m-passes/24h01m-fails boundary), 0 missing
- validations[] conditions: 22 checked, 22 matchable to error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed (depth-3 closure chain with suppressed bed-release compensation, discharge cascade, WAC388-76-10 auto-suspend, terminate cascade, counter recomputations), 0 missing
- entities[].fields[] structured content: defaults (timezone, medicaid_certified, awake_overnight_qualified, late_fee_cents=0), ranges (2–6 beds, 0–40h, 0–6 ADL, 1–6 schedule_times, ≤16h), enum sets, append-only exceptions — all reconstructible, 0 missing
- sibling-branch symmetry: 8 groups checked (close from LICENSED/SUSPENDED; substantiate/unfound; case-close branches; provisional/final; medicaid/private_pay; day/overnight staffing; reject/cancel compensation; ISSUED→PAID direct vs cumulative), 0 asymmetric
- Status: PASS

Path purity check (§3 only, Contract 3):
- backtick tokens scanned: 426
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
- Status: PASS
```

Additional checks: all 23 `errors[].id` appear in §2/§3 prose; all 66 enum/state values appear as exact strings; no pseudocode operators or fuzzy hedging words in prose; no audit footer in the file.

**Adjudications made:** (1) Scaffold validation priority 22 places `ERR_INVALID_REQUEST` (structural payload validity) *last* in the pipeline — rendered faithfully rather than reordered to conventional validate-first semantics. (2) The scaffold's self-negating admission-completion note about delinquent final bills was rendered as an explicit non-check: "a delinquent prior final invoice does not block completion." (3) "CRITICAL also suspends new admissions" (severity field semantics) was projected via the scaffold's only enforcement path — the WAC388-76-10 substantiation cascade to home `SUSPENDED`, which blocks approvals — rather than inventing a new admission-time rule. (4) SUSPENDED-caregiver scheduling rejection is attributed to `ERR_INVALID_STATE` as the catalog's declared generic fallback, since no more specific error exists in the scaffold.

## Step 5: Generate Unit Tests — 2026-08-10T07:35:00.000Z

## Stage 2 Audit Summary — task_0971 (adult family home residential care)

### Queue counts

**§1.8 Difficulty (queue A): 18 instances — 18 emitted, 0 skipped.**
Each emitted instance received exactly 2 tests (36 queue-A tests total). All 18 passed the PRD-first two-condition filter: every asserted error_id, threshold, transition, cascade link, and literal subtotal has verbatim rule-bearing PRD prose (§2.5–§2.11, §3.1–§3.8) and a uniquely derivable outcome.

**§1.9 Corner (queue B): 82 instances — 64 non-stub emitted (79 tests), 18 stub-skipped, 0 filter-skipped.**
All 18 `excluded_because:` stubs were left untranslated; every stub's `difficulty_instance` cross-reference was verified to resolve to a real §1.8 `name:` (0 broken pointers). Non-stub instances with assertion bundles split across 2–3 tests: `home_bed_capacity_bounds_enforced`, `home_license_requires_bed_and_active_caregiver`, `home_terminal_closed_lockdown`, `resident_withdraw_returns_prospect`, `bed_held_take_out_of_service_forces_admission_rejected`, `med_window_refused_does_not_consume_window`, `minor_incident_close_succeeds_without_case`, `shift_created_in_scheduled_initial_state`, `discharge_cascades_bed_release_and_order_discontinue`, `discharge_records_listable_after_discharge`, `get_nonexistent_resources_return_404`, `nurse_can_create_and_finalize_assessment` (each split shares one Design tag per test).

**Skip rationale:** none — no instance was filter-skipped. No `pytest.mark.skip`/`skipif`/`xfail` exists anywhere in the suite.

### Setup-plumbing adaptations (assertions unchanged, noted for transparency)
1. `partial_payments_conserve_invoice_total` — the recipe's issue clock `2026-06-21T00:00:00Z` is home-local date 2026-06-20 == due_date, which under PRD §3.8's strictly-greater home-local-date rule yields no fee, contradicting the pinned 7500. Issue clock moved to `2026-06-22T00:00:00Z` (home-local 06-21 > due_date) so the pinned assertions (fee 7500, total 157500, PAID at 157500) hold.
2. `caregiver_overlap_touch_allowed_rolling16_accumulates` — the recipe's first two shifts cover part of the 22:00–06:00 home-local overnight window, for which PRD §3.5 makes `overnight_mode` required; supplied `overnight_mode="AWAKE"` (caregiver awake-qualified, census 0 → no staffing interaction). Rolling-24h arithmetic and the ERR_SHIFT_CONFLICT assertion are untouched.

### Per-file test counts (test_suite/)
- test_01_home_registration_and_licensing.py: 12
- test_02_bed_service_and_holds.py: 9
- test_03_residents_and_admissions.py: 15
- test_04_assessments_and_clinical_rbac.py: 4
- test_05_medication_and_adl_logging.py: 10
- test_06_shifts_and_staffing.py: 10
- test_07_incidents_and_compliance.py: 14
- test_08_billing_rates_and_payments.py: 8
- test_09_billing_fees_and_settlement.py: 16
- test_10_discharge_workflows.py: 10
- test_11_auth_and_validation_pipeline.py: 7

**Total: 115 tests** (36 tagged Difficulty, 79 tagged Corner).

### Verification results
- `python3 -m pytest test_suite/ --collect-only -q` from the task dir: **115 collected, 0 errors**.
- Tag audit: every one of the 115 test functions carries **exactly one** `Design:` docstring line; all 115 tags resolve to real instances in the source YAMLs; 0 untagged/dual-tagged/unresolved.
- Coverage audit: every §1.8 instance has ≥2 tests; every non-stub §1.9 instance has ≥1 test. No shortfalls.
- PRD-citation sweep: 172 quoted citation sentences extracted from docstrings; **all 172 survive verbatim grep** of `workspace/PRD.md` (whitespace/backtick-normalized). 0 non-verbatim.
- Hygiene: no "scaffold" references in generated code; `test_helpers/` and `test_suite/` both exist on disk; `test_helpers` imports cleanly (77 ApiClient endpoint methods; append-only entities — MedicationLog, ADLLog, Payment, DischargeRecord — modeled without `updated_at`/`version` per PRD §2.5).

## Step 6: Generate Implementation — 2026-08-10T07:35:00.000Z

## File layout (`workspace/implementation/`, ~2.5k lines)

- `start.sh` — guarded install (`if ! python3 -c "import flask"`), `exec python3 app.py`, foreground
- `requirements.txt` — flask only
- `app.py` — Flask factory, envelope-shaped error handlers (incl. 404/405), `static_folder=None` so no extra route
- `db.py` — in-memory store (16 dicts, empty at boot, no seeding) + logical clock pinned at 2026-05-01T00:00:00Z
- `errors.py` — full 23-code catalog with HTTP statuses
- `util.py` — envelope (`meta.api_request_id/api_request_timestamp`, `response_type`, `data`; list pagination fields in `meta`), ms-precision timestamps, pagination (limit default 10, 1..100, offset), auth decorator (`X-User-Role`/`X-User-ID`), structural validators
- `logic.py` — derived counters, cascades (home close depth-3, bed-OOS forced rejection, discharge), staffing-ratio segment engine, rolling-16h/overlap, med windows, Medicaid acuity/late-fee math (Decimal, ROUND_HALF_UP/truncation), discharge refund waterfall
- `routes_a..e.py` — clock/homes/beds; residents/assessments/admissions; meds/ADL/caregivers/shifts; incidents/compliance; rates/invoices/payments/discharge-records

## Route count

**73/73 exact match** — programmatic diff of the Flask url_map against SCAFFOLD.yaml's endpoint list (method + path with `{id}`↔`<id>` normalization): no missing, no extra.

## Boot verification

`PORT=18799 bash start.sh` from a fresh process → 200 on `GET /api/homes` within ~2s with the correct envelope and an empty store, then killed. Two self-built verification suites passed end-to-end on fresh boots: a main smoke (clock, licensing, admission pipeline with OCC/SoD, billing, med windows, incident→case→abuse-suspend→reinstate, discharge refund, closure cascade, pagination) and an edge suite (Medicaid band/nursing-cap math, supersede→ERR_ASSESSMENT_SUPERSEDED, capacity 409, rolling-16h, overnight AWAKE/ASLEEP staffing, late-fee boundary, 24h00m vs 24h01m deadline boundary, forced rejections).

## Key PRD-interpretation adjudications

1. **X-User-ID required for all roles** (PRD §2.1 sentence 1 is unconditional), but resolvable-to-entity only for `CaregiverRole`; unknown caregiver id → 401.
2. **CaregiverRole ownership**: on med/ADL log creation, body `caregiver_id` must equal `X-User-ID` else 403; not enforced on reads.
3. **Staffing gate scope**: create/cancel validate the *affected shift's own window* (clipped to ≥ logical now) against post-change coverage, with uncovered sub-segments non-compliant when census>0 (a lone-shift cancel is rejected; a gap between shifts never creates phantom segments). The GET staffing-compliance endpoint emits union segments only (gaps excluded).
4. **Validation pipeline**: structural validity (400) is genuinely last per §2.9 — e.g. a >16h shift returns ERR_SHIFT_CONFLICT (rolling cap, step 10) since any >16h shift necessarily trips the cap; OCC mismatch (412) only when the expected field is present, absence falls through to 400.
5. **Admission approve check order** per §3.3 narrative: PENDING → self-approval → home LICENSED → assessment currency → bed HELD.
6. **Discharge refund**: per-invoice prepaid pool = min(payments on invoice, R&B-line amounts dated strictly after the home-local discharge date); waterfall over ISSUED/PARTIALLY_PAID balances ordered by (period_start, created_at); floor 0.
7. **Second open-case on a reopened incident** (live OPEN case exists) → 409, preserving one-case-per-incident uniqueness.
8. Line-item `description` is `"room_and_board"` for every occupied day (both payers), giving the refund a deterministic line selector; provisional vs final invoice windows diverge solely through `discharged_at` per the identical day-inclusion formula.

## Step 7: Run Tests and Iterate — 2026-08-10T07:40:00.000Z

## Summary

**Iterations run:** 2 (first sweep: 7 stable failures × 8 rounds; second sweep: all 8 rounds clean at 115/115).

**Tests deleted:** none. Every failing test traced to verbatim PRD prose; the four timestamp tests had partial coverage and were split per STEP 1c (PRD-covered instant kept, PRD-silent string rendering dropped).

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_0971_adult_family_home_residential_care/test_helpers/assertions.py` — added `assert_same_instant(actual, expected)`, which parses both ISO 8601 timestamps and compares instants. Why: PRD pins the *instant* of clock-stamped/computed fields (`correction_plan_due_at` = decision + 14 days, `discharged_at` "from the clock") but does not uniquely determine the string rendering — the implementation's `.000Z` form matches PRD's explicit "three fractional digits" convention for `created_at`/`updated_at`/`api_request_timestamp`, while the test's bare `Z` form matches the clock's display format; both are faithful readings, so exact string equality failed unique derivability.

**Fixes applied to `test_suite/`:**
- `test_05_medication_and_adl_logging.py` (test_window_lower_edge_inclusive_accepted) — `administered_at` echo compared by instant instead of raw string.
- `test_07_incidents_and_compliance.py` (test_correction_plan_due_fourteen_days_after_decision, test_late_correction_plan_rejected) — `correction_plan_due_at` compared by instant.
- `test_10_discharge_workflows.py` (test_discharge_stamps_discharged_at_from_clock) — `discharged_at` on resident and discharge record compared by instant.

**Fixes applied to `implementation/`:**
- `workspace/implementation/routes_d.py`, `open_case()` — after a PRD §3.6 reopen (`UNDER_REVIEW → REPORTED`, case stays `OPEN`), a second `POST /incidents/{id}/open-case` previously returned 409 `ERR_INVALID_STATE`. PRD's endpoint table lists `REPORTED → UNDER_REVIEW` with only "late reports refused", and "exactly one case per incident" forbids a duplicate — so the handler now re-links the existing `OPEN` case, moves the incident back to `UNDER_REVIEW`, and returns it with 201. The late-report check and the non-OPEN live-case guard are preserved.
- `workspace/implementation/routes_a.py`, `staffing_compliance()` — the forward-visibility endpoint called `build_segments(...)` without `include_uncovered=True`, so a supplied window with zero covering shifts produced zero segments and vacuously reported `compliant: true`. PRD §3.5 ("run the same ratio evaluation over a supplied window"; "a segment whose on-duty coverage falls below its requirement is non-compliant"; §1 "every overnight hour must satisfy staffing-ratio rules") requires uncovered occupied time to report non-compliant; the endpoint now passes `include_uncovered=True`.

Orchestrator verification: all 8 `workspace/implementation/results.{1..8}.json` files present on disk, every round `passed=115 total=115 failed=0` — ALL_PASS.

## Step 8: Finalize PRD — 2026-08-10T07:50:00.000Z

All four edits are in place and the diff is exactly scoped. Final verification is complete — PRD_FINALIZED.md is written at the target path.

## Summary

**Line counts:** PRD.md = 348 lines; PRD_FINALIZED.md = 348 lines (0.0% line-count delta; 4 lines revised in place, no lines added or removed — all edits were inline sentence insertions/revisions per the "no new sections" constraint).

**Changes (4 edits, each traced to a `<step_7_diff>` item):**

- **§2.4 The Logical Clock — insert** — pinned the global timestamp rendering convention: every timestamp the API emits (clock-stamped/computed fields, `current_utc`, `created_at`/`updated_at`, and echoes of client-supplied timestamps) renders as ISO 8601 UTC with exactly three fractional digits and trailing `Z` (initial clock renders `2026-05-01T00:00:00.000Z`) — `implementation/util.py:23-25` (`fmt_ts`, the single choke point); covers the `assert_same_instant` helper addition and the three test-side fixes (test_05 `administered_at` echo, test_07 `correction_plan_due_at` ×2, test_10 `discharged_at` ×2).
- **§3.6 Incidents and State Compliance Cases — insert** — pinned the second open-case after a reopen: not an error, no second case, incident moves `REPORTED` → `UNDER_REVIEW` again, existing `OPEN` case returned with 201, home counters untouched — `implementation/routes_d.py:103-110` (the Step 7 re-link branch in `open_case()`).
- **§4 Endpoint table, `POST /api/incidents/{id}/open-case` row — revise** — companion wording to the §3.6 edit: "or, when the linked case is still `OPEN` after a reopen, returns that same case with 201 instead of creating a second one" — `implementation/routes_d.py:91-129`.
- **§3.5 Staffing — revise (sentence appended to the forward-visibility sentence)** — pinned that the staffing-compliance evaluation spans the whole supplied window: uncovered stretches appear as zero-on-duty segments, non-compliant whenever census is above zero, and `compliant` is true only when every segment is compliant — `implementation/routes_a.py:170` (`include_uncovered=True`), `implementation/logic.py:157-194`.

**Per-edit pre-edit search log:**

1. **§2.4 timestamp edit** — (a) Subject: string rendering of every emitted timestamp. (b) Enumerated: `util.py:23-25` (`fmt_ts` definition), `util.py:51-52` (`now_ts`), `util.py:63` (`api_request_timestamp` — wall clock, rendering-only claim kept clock-source-neutral to avoid mis-describing it), `util.py:89-102` (`stamp_new`/`touch`), `routes_a.py:41` (`current_utc`), `routes_b.py:129/159/187/337/350/364/389` (`discharged_at` ×2, `assessed_at`, `decided_at` ×3, `admitted_at`), `routes_c.py:170/233/433-434` (`administered_at`, `performed_at`, shift `start_at`/`end_at` echoes), `routes_d.py:60/62/206/258` (`occurred_at`, `reported_at`, `correction_plan_due_at`, `correction_plan_submitted_at`), `routes_e.py:260` (`received_at`), `logic.py:55/188-189` (system `decided_at`, segment bounds). Date-only fields (`date_of_birth`, `effective_from/to`, `period_start/end`, `due_date`, line `day`) verified as dates, not timestamps, and excluded from the claim. (c) Wording widened to "every timestamp the API emits" with explicit enumeration of echo fields, and scoped to rendering only (not clock source) so `api_request_timestamp` stays correctly described by §2.2.
2. **§3.6 + endpoint-table edits** — (a) Subject: open-case behavior when the linked case is still `OPEN` after a reopen. (b) Enumerated: `routes_d.py:91-129` (`open_case` — all four branches, including late-check ordering and the unreachable CLOSED-case fall-through), `routes_d.py:132-170` (`reopen`, `close`, `close-minor`), `routes_d.py:196-264` (substantiate/unfound/close — unaffected), `routes_d.py:30-34` (`_linked_case`), `logic.py:31-38` (`recompute_home_counters` — called only in the create branch). (c) Wording scoped with "while that case is still `OPEN`" to avoid a universal no-second-case claim (the impl's CLOSED-case branch would technically create one); added "leaving the home's counters untouched" to match the branch's absence of a home mutation, and left the late-check ordering unpinned since it is unobservable (a late incident can never hold an `OPEN` case).
3. **§3.5 staffing endpoint edit** — (a) Subject: endpoint treatment of window sub-intervals with zero covering shifts. (b) Enumerated: `routes_a.py:154-172` (endpoint; `to > from` enforced so the segment list is never empty — `compliant = all(...)` is never vacuous), `logic.py:157-194` (`build_segments` — uncovered segments compliant when census = 0, since requirement collapses to 0 for both DAY and OVERNIGHT), `logic.py:197-209` (`forward_staffing_ok` — same `include_uncovered=True` semantics on the create/cancel path, keeping "the same ratio evaluation" accurate), `routes_c.py:361-442, 464-478` (shift create/cancel callers). (c) Wording qualified with "whenever the home's census is above zero" to match the census-0-compliant behavior, and avoided enumerating segment fields or cut points beyond what PRD already pins.

No other `<step_7_diff>` items required PRD edits (no test deletions occurred; the helper/test fixes were pure unique-derivability corrections fully covered by edit 1).

## Step 9: Complete PRD — 2026-08-10T08:00:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_0971_adult_family_home_residential_care/workspace/PRD_COMPLETED.md` is written (348 lines, same as PRD_FINALIZED.md's 348 — all changes are inline, no new sections; 50170 → 53785 chars, +3615).

**Counts: 30 ambiguity-pins, 3 mismatch-revisions (33 changes total, via 20 inline edits).**

Ambiguity-pins (insert):

- §2.1 — insert — ambiguity — `X-User-ID` is required on every request for every role (missing → 401); "unresolvable" applies only to CaregiverRole — util.py:158-163
- §2.1 — insert — ambiguity — CaregiverRole logging with a `caregiver_id` ≠ own `X-User-ID` → `ERR_UNAUTHORIZED` — routes_c.py:38-43
- §2.2 — insert — ambiguity — `api_request_timestamp` is generated from the wall clock, not the logical clock — util.py:59-64
- §2.3 — insert — ambiguity — non-integer `limit`/`offset`, `limit` outside [1,100], negative `offset` → `ERR_INVALID_REQUEST` — util.py:118-136
- §2.3 — insert — ambiguity — sort ties on identical `created_at` break by server creation order — util.py:111
- §2.3 — insert — ambiguity — `has_more` = `offset` + returned items < `total_count` — util.py:143
- §2.4 — insert — ambiguity — `created_at`/`updated_at` added to the enumeration of fields read from the logical clock — util.py:91-101, db.py:33-37
- §2.5 — insert — ambiguity — `version` starts at 1 at creation — util.py:95
- §2.10 — insert — ambiguity — body identifier belonging to a different parent (assessment/resident, caregiver/home, order/resident, invoice/resident) → `ERR_NOT_FOUND` — routes_b.py:254-256, routes_c.py:128-129, routes_c.py:369-370, routes_e.py:238-239
- §3.1 — insert — ambiguity — duplicate `license_number` → `ERR_INVALID_REQUEST` — routes_a.py:64-66
- §3.1 — insert — ambiguity — `licensed_bed_capacity` outside 2–6 → `ERR_INVALID_REQUEST` — routes_a.py:55-56
- §3.1 — insert — ambiguity — `timezone` must be a valid IANA name → `ERR_INVALID_REQUEST` — routes_a.py:57-63
- §3.1 — insert — ambiguity — duplicate bed `label` within a home → `ERR_INVALID_REQUEST` — routes_a.py:186-188
- §3.1 — insert — ambiguity — duplicate `credential_id` across homes → `ERR_INVALID_REQUEST` — routes_c.py:272-274
- §3.1 — insert — ambiguity — cascade-forced rejection records `decided_by` as the literal string `system` — logic.py:54
- §3.2 — insert — ambiguity — `nursing_hours_per_week` accepts fractional numeric values in [0,40] — routes_b.py:175-177
- §3.2 — insert — ambiguity — `care_plan` is validated only as a JSON object; internal fields not inspected — routes_b.py:181-183
- §3.3 — insert — ambiguity — pinned assessment not `FINALIZED` at creation → `ERR_INVALID_STATE` — routes_b.py:268-269
- §3.3 — insert — ambiguity — admission creator `X-User-ID` recorded internally, never exposed in responses — routes_b.py:292, util.py:105-107
- §3.4 — insert — ambiguity — med-order creation on a non-`ADMITTED` resident → `ERR_INVALID_STATE` — routes_c.py:67-68
- §3.4 — insert — ambiguity — `schedule_times` entries must be `HH:MM` 24-hour strings; malformed entry or list outside 1–6 → `ERR_INVALID_REQUEST` — routes_c.py:46-56, 72-76
- §3.4 — insert — ambiguity — on-shift verification requires the shift at the resident's home — logic.py:269-275
- §3.5 — insert — ambiguity — forward staffing evaluation runs over the shift's own span clipped to ≥ current logical time; entirely-past shifts pass; census-zero homes pass unconditionally — logic.py:197-209
- §3.5 — insert — ambiguity — staffing-compliance: both window params required, `to` strictly after `from` else `ERR_INVALID_REQUEST`; per-segment fields `start_at`/`end_at`/`period`/`on_duty`/`required`/`compliant` — routes_a.py:154-172, logic.py:186-193
- §3.6 — insert — ambiguity — incident late flag is internal, not part of the response body — routes_d.py:55-67, util.py:105-107
- §3.7 — insert — ambiguity — present `effective_to` must be strictly after `effective_from` → `ERR_INVALID_REQUEST` — routes_e.py:81-82
- §3.7 — insert — ambiguity — `ERR_RATE_OVERLAP` evaluated ahead of structural payload validity — routes_e.py:44-64
- §3.7 — insert — ambiguity — generation rejected with `ERR_INVALID_STATE` unless resident is `ADMITTED`/`DISCHARGED`, and when no `FINALIZED` assessment exists — routes_e.py:126-128, logic.py:334-335
- §3.8 — insert — ambiguity — refund pool draws only from `ISSUED`/`PARTIALLY_PAID`/`PAID` invoices, each capped at min(payments received, post-discharge room-and-board lines) — logic.py:385-398
- §3.8 — insert — ambiguity — discharge returns the created discharge record (which also carries `resident_id`) with 200 — routes_b.py:155-163

Mismatch-revisions (revise):

- §2.4 — revise — mismatch — clock endpoint "advances" → sets the clock to any supplied instant, later or earlier, returning 200 — routes_a.py:31-41
- §3.3 — revise — mismatch — admission completion applies the capacity check before verifying the bed remains `HELD` (impl order, contra §2.9's generic 5-before-19) — routes_b.py:380-384
- §3.7 — revise — mismatch — `line_items`: exactly one row per occupied day, `description` `room_and_board`, `qty` 1, `unit_price_cents` = full combined daily rate, no ancillary rows (replacing "room-and-board or acuity-band care — plus flat ancillary rows") — logic.py:352-359
