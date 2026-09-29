# Worklog — task_2506_homeowner_rehabilitation_loan_program

## Step 1: Create task directory — 2026-09-03T02:48:56.418Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2506_homeowner_rehabilitation_loan_program` and its `workspace/` subdirectory. Index 2506 was pre-assigned by the invoking pipeline; no scan of ./tasks/ was performed (concurrent pipelines on this host would collide with auto-allocation).

## Step 2: Generate scaffold — 2026-09-03T04:14:47.864Z

Scaffold artifacts complete and lint-clean.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2506_homeowner_rehabilitation_loan_program/`): `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`

**Lint**: `VERDICT: clean lint` — 798 calls scanned across §1.8+§1.9, all resolve to §1.5 (method, path, roles, payload keys, captures, `expected_*_version` interpolation), all §1.1 FKs reverse-reachable.

---

### Summary for worklog.md

**task_2506_homeowner_rehabilitation_loan_program** — CDBG housing rehabilitation loan program (`api_prefix: /rehab`).

**Complexity profile**: primary archetype `compliance_audit`, secondary `multi_party_negotiation`; layers `dual_variant_calculation`, `cascading_side_effects`, `rate_threshold_triggers`, `optimistic_concurrency`; entity topology `flat`, state-machine shape `cyclic`, role model `segregation_of_duties`, consistency `immediate`.

**SCAFFOLD.yaml (§1.0–§1.7)**
- **13 entities**: ProgramYear, Applicant, RehabApplication, PropertyInspection, WorkWriteUp, WorkItem, Contractor, BidSolicitation, Bid, RehabLoan, DrawRequest, ChangeOrder, ComplaintCase
- **12 state machines** (cyclic: solicitation reopen cycles, contractor probation/reinstatement)
- **2 concurrency rules**: `write-up-revision-stale-application` (`expected_application_version`), `change-order-stale-loan` (`expected_loan_version`) — both ERR_STALE_VERSION/412
- **9 calculations**: Part 5 vs IRS-1040 income variants + AMI percent/category, write-up estimate with contingency, bid responsiveness band, recording-fee tier + loan principal, change-order cumulative ceiling, draw retainage/net payment, program-year committed/uncommitted triad, recapture (sale vs transfer variants), contractor weighted performance score
- **31 validations**, **65 endpoints**, **42 errors** (401/403/400/412/404×13/409×14/422×9), **7 roles** (Applicant, Contractor entity-backed; IntakeSpecialist, RehabSpecialist, Inspector, LoanOfficer, ProgramManager operators with segregation of duties between write-up preparer and approver)
- Pagination: limit default 10 (1–100), offset 0

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)**: 9 rules × 2 instances = **18 instances**, each with a full structured `setup_api_calls` chain and literal asserts.

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9)**: all **9 guide sections**, **72 instances** = 48 real `test_recipe`s + 24 `excluded_because` stubs (each citing an existing §1.8 instance):
- entities 12 (12 real), state_machines 14 (7 real / 7 stubs), calculations 8 (3/5), validations 12 (8/4), endpoints 5 (5 real), errors 12 (6/6), rbac 4 (4 real), cross_cutting_complexity_layers 4 (2/2), consistency_model 1 (1 real)
- Heaviest recipes: the OCC stale-version retry (asserts `version` advances by exactly 2), the four-hop cascading side effect, and the full 27-call lifecycle-to-CLOSED chain driving the performance score 100 → 85 → 65 → 45 with automatic APPROVED→PROBATION only at the third open complaint (and no automatic promotion on remedy).
- Name uniqueness verified across the union of both design files; no `scaffold_difficulty_design`/`scaffold_corner_design` keys leaked into SCAFFOLD.yaml.

Line counts: SCAFFOLD.yaml 3336, SCAFFOLD_DIFFICULTY_DESIGN.yaml 2244, SCAFFOLD_CORNER_DESIGN.yaml 3133.

## Step 3: Copy shared files — 2026-09-03T04:15:09.652Z

Copied `./INSTRUCTION.md` → `tasks/task_2506_homeowner_rehabilitation_loan_program/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T04:30:15.678Z

All checks pass. Verification results:

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2506_homeowner_rehabilitation_loan_program/workspace/PRD.md`

**Completeness:** 500 lines. Last section heading is `## 5. Error Code Catalogue`; the file ends at a real boundary — the final line is the closing table row `| \`ERR_APPLICANT_OVER_INCOME\` | 422 |`. No scaffold section dropped: 13 entities, 12 state machines (71 transitions), 2 concurrency rules, 9 calculations, 31 validations, 65 endpoints, 42 errors, 7 roles all rendered. Structure: §1 Introduction, §2 with 11 subsections (2.2 pasted verbatim), §3 with 9 workflow subsections, §4 with 65 endpoint rows, §5 with 42 error rows.

```
Field coverage check:
- entities[].fields: 166 required, 166 present, 0 missing
- endpoints[].request_body: 91 required, 91 present, 0 missing
- endpoints[].query_params: 25 required, 25 present, 0 missing
- path parameters: 13 required, 13 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 31 checked, 31 expressed in prose (ordered 1-31 in §2.11), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + error_id all named), 0 missing
- state_machines[].transitions: 71 checked, 71 fully expressed, 0 missing
- calculations[]: 9 checked, 9 fully expressed, 0 missing
- validations[] conditions: 31 checked, 31 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 65 endpoints + 31 applies_to scopes checked, all expressed, 0 missing
- entities[].fields[] structured content: 166 checked, 166 reconstructible from prose, 0 missing
- sibling-branch symmetry: 14 groups checked, 14 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 875
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional mechanical validations run: all 65 §4 rows match scaffold method+path exactly and their Authorized Role(s) cells match `endpoints[].roles` set-for-set (0 mismatches); all 42 §5 rows match scaffold `errors[].http` (0 status mismatches, 0 duplicates); all 59 enum member names across entity fields appear verbatim in the prose.

Notes on scaffold internal conflicts resolved (flagging for the test-suite step): (1) `ChangeOrder.cumulative_delta_pct` field text says 4 decimals while the calculation says `round_half_up_2dp` with a 20.00 gate — PRD states two decimals; (2) `Bid.proposed_end_date` field text says "strictly after" start while validation priority 6 and the `ERR_INVALID_REQUEST` condition allow equality — PRD states "not earlier than"; (3) the `loan_structuring` DEFERRED branch sets `forgiveness_term_months = 0` while the field constraint requires it > 0 for DEFERRED — PRD follows the field constraint (positive, stored as supplied). The difficulty meta-line at the head of `scenario` was excluded; `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened.

**Orchestrator truncation check (per known doc-generator failure mode):** independently verified — `wc -l` = 500; tail ends on a complete markdown table row of §5; heading scan shows §1–§5 all present; §4 endpoint row count = 65 (matches scaffold), §5 error row count = 42 (matches scaffold); grep for `harder than expert` / `expert level` / `difficulty` in PRD.md returns nothing, so the Step 2-only difficulty instruction did not leak. No regeneration needed.

## Step 5: Generate unit tests — 2026-09-03T06:06:10.629Z

(Steps 5 and 6 were launched concurrently in a single assistant message, giving the impl generator physical isolation from `test_suite/`, which did not exist when it started.)

Generation is complete. Final audit passes clean.

## Summary — task 2506 (Homeowner Rehabilitation Loan Program) test generation

**Files written**

`test_helpers/` (Stage 1, 9 files, verified importable): `__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`

`test_suite/` (Stage 2, `conftest.py` + 15 test modules):
- Queue A (§1.8 depth): `test_01_income_certification.py` (7), `test_02_work_write_up_scope.py` (6), `test_03_property_inspections_and_compliance.py` (8), `test_04_bid_solicitation_and_award.py` (5), `test_05_loan_structuring_and_liens.py` (7), `test_06_construction_draws.py` (6), `test_07_settlement_and_program_income.py` (6), `test_08_contractor_standing_cascades.py` (6)
- Queue B (§1.9 breadth): `test_09_resource_lifecycle_corners.py` (12), `test_10_state_transition_corners.py` (7), `test_11_estimate_and_pricing_corners.py` (7), `test_12_validation_gate_corners.py` (9), `test_13_endpoint_behavior_corners.py` (8), `test_14_error_reachability_corners.py` (13), `test_15_access_and_consistency_corners.py` (10)

**Counts**
- Queue A: 51 test functions over 17 of 18 non-stub difficulty instances (every covered instance has ≥2 tests).
- Queue B: 66 test functions over 47 of 48 non-stub corner instances (≥1 each); the 24 `excluded_because:` stubs emit nothing.
- Total 117 functions, 130 collected cases (parametrize expansion), `pytest --collect-only` clean in 0.61s.

**Audit results**
- Every test carries exactly one `Design:` line, and it is the last line of the docstring; 64 distinct tags, all resolving to real non-stub instances in the correct queue/section; zero untagged, dual-tagged or dangling tags.
- Every `PRD: "..."` quote is verbatim in `workspace/PRD.md` and is a complete sentence (I extended eight quotes in test_01/02/03/04/05 that had been clipped mid-sentence).
- No generated text mentions the scaffold, scaffold sections or scaffold constant names; the three `§` occurrences are inside verbatim PRD quotes (the PRD's own cross-references).

**Instances skipped (PRD-first filter, gaps left as gaps — no xfail, no placeholder)**
1. `Difficulty/resource_temporal_overlap/contractor_award_capacity_uses_closed_buffered_windows_so_touching_windows_conflict` — the design inflates both construction windows by the crew buffer; PRD §3.5 inflates only the incoming bid's window, so the design's touching pair does not conflict and the asserted `ERR_CONTRACTOR_CAPACITY_CONFLICT` is not uniquely derived.
2. `Corner/validations/lead_certification_is_required_only_where_the_lead_protocol_fired` — needs a RESPONSIVE bid from a non-lead-certified firm on a lead-protocol case, but PRD §3.5 tabulation condition 4 classifies exactly that bid `NON_RESPONSIVE` (`NOT_LEAD_CERTIFIED`), and no endpoint mutates `lead_safe_certified`, so the award-time 422 `ERR_CONTRACTOR_NOT_LEAD_CERTIFIED` is unreachable.

**Design drift corrected in favour of the PRD** (instances kept, individual limbs fixed): `ERR_LOAN_LIMIT_EXCEEDED` fires at loan structuring, not at award; `ERR_DRAW_EXCEEDS_CONTRACT_BALANCE` fires at draw approval, not draw creation (the lien gate stays at creation); field names `lien_recording_fee_cents` / `principal_cents`; enum values `HVAC`, `ACCESSIBILITY`, `NO_ADVERSE_EFFECT`; dropped the design's non-PRD `low_bid_amount_cents` assertion; dropped the "Contractor reading another firm's bid → `ERR_OWNERSHIP_MISMATCH`" and "unknown id → 404 for a peer applicant" limbs (priority 3 enumerates five scoped operations, and §2.1 says the 403 does not disclose existence); replaced the "successful revision bumps the version again" limb with the change-order `expected_loan_version` limb (§3.3 bumps the case only for a *later* revision).

Note: the suite has never been executed against a live server — no implementation directory was read or touched.

## Step 6: Generate implementation — 2026-09-03T06:06:10.629Z

Implementation complete and verified green end to end.

## Files written

`/home/ubuntu/github/CodingPRD/tasks/task_2506_homeowner_rehabilitation_loan_program/workspace/implementation/` — 26 files, 4,111 lines of Python.

- `start.sh` — `exec python3 app.py`, foreground, guarded `pip install` (only when Flask is missing, to avoid boot contention under 8 concurrent per-test reboots)
- `requirements.txt` (Flask 3.0.3), `app.py` (factory, blueprint registration, error handlers, global-lock WSGI middleware)
- Infrastructure: `db.py`, `clock.py`, `errors.py`, `response.py`, `validation.py`, `middleware.py`, `paging.py`
- `services/`: `constants.py`, `calc.py`, `serializers.py`, `domain.py`
- `routes/`: `clock_routes.py`, `program_years.py`, `applicants.py`, `applications.py`, `inspections.py`, `write_ups.py`, `contractors.py`, `solicitations.py`, `loans.py`, `draw_requests.py`, `change_orders.py`, `complaints.py`

## Endpoint count

**65** method+path pairs, all under `/rehab` (clock 1, program-years 3, applicants 5, applications 6, inspections 4, write-ups + work-items 10, contractors 4, solicitations + bids 9, loans 7, draw-requests 5, change-orders 5, complaints 6).

## Notable design decisions

- **Storage**: 13 in-memory dicts in `db.py`. No SQLite, no disk, no `/tmp`. Nothing is seeded — every collection is empty on boot and the clock reads exactly `2026-08-01T00:00:00.000Z`.
- **Money**: `Decimal` + `ROUND_HALF_UP` throughout (`getcontext().prec = 60`); never float, never banker's `round()`.
- **§2.11 numeric precedence is the single authority**, overriding prose that implied a different order in §3.5 and §3.7. Award = state(8) → capacity(18) → responsive(26) → approved list(27) → lead cert(28). Change-order approve = state(8) → allocation(21) → cumulative limit(23). Draw approve = lead clearance(11) → draw inspection passed(13) → SoD(15) → contract balance(22).
- **Draw approval is carved out of the generic priority-8 state rule**, so a draw in `SUBMITTED`, `INSPECTION_FAILED`, `APPROVED` or `PAID` all return `ERR_DRAW_INSPECTION_NOT_PASSED`.
- **`contract_earned_cents` posts at payment**, not approval (PRD §3.7 hop one) — required by the loan conservation identity `contract_earned + lien_recording_fee == disbursed + retainage_held`.
- **Derived vs stored**: committed/disbursed/uncommitted and the contractor counters (`open_complaint_count`, `performance_score`, `active_award_count`) are computed live; solicitation `bid_count`/`responsive_bid_count` are stored counters. A program year's `version` advances only when its derived ledger actually moves.
- **Atomicity**: one global `RLock` around the WSGI app, so each multi-hop cascade is indivisible.
- **Unnamed preconditions** → `ERR_INVALID_STATE` 409; uniqueness violations (fiscal year, applicant email, contractor license) → `ERR_INVALID_REQUEST` 400. Ownership scoping is enforced on exactly the five §2.11 operations.

## Verification

`bash start.sh` boots in the foreground, binds `0.0.0.0:$PORT` (confirmed via `ss -lntp`), and answers requests. A 200-step end-to-end smoke harness (throwaway, at `/tmp/rehab_smoke.py`, not part of the deliverable) drives two full cases — intake → income verification → ownership → inspection → lead clearance → write-up revision cycle → solicitation/tabulation/award → loan structuring → lien → two draws → three change orders (including a supersedes chain and a limit breach) → close-out → payment → complaint → sanction → recapture, plus a failed-solicitation/reopen path and the auth/envelope edges — and reports **failures: 0**, with every ledger, loan and settlement identity balancing. Both smoke servers were shut down cleanly by port-scoped kill (never `pkill -f app.py`, which kills tracked background tasks), `__pycache__` was removed, and both ports are free.

Two mid-run failures were both defects in the smoke harness, not the server, and were confirmed against SCAFFOLD.yaml before being fixed there: a missing `ownership_doc_type` on intake plus a `title_clear`/`title_report_clear` key name, and a draw re-inspection reserved by one inspector but recorded by another (PRD §3.2: only the inspector who reserved the visit may record its result).

## Step 7: Run tests and iterate — 2026-09-03T06:37:44.832Z

Green. All 8 rounds of the final sweep verified on disk.

## Summary

**Iterations run:** 3 (each an 8-round parallel `setsid nohup` sweep, `--isolation per-test-server`)
- Iteration 1: 8/8 rounds `124/130` — 6 identical failures in every round (deterministic, not load-induced)
- Iteration 2: 8/8 rounds `129/130` — 1 failure, newly unmasked behind a previously-tripping assertion
- Iteration 3 (final): 8/8 rounds `130/130`, 0 failed / 0 errors / 0 skipped, ~227 s per round

**Tests deleted:** none. Every failure traced to a test-layer defect, not to a PRD-silent assertion.

**Fixes applied to `test_helpers/`**
- `test_helpers/assertions.py` — new `assert_instant(data, field, expected)` (plus `_instant` parser): asserts a timestamp field denotes an expected instant while tolerating either rendering. PRD §2.5/§2.2 fix the three-fractional-digit format for `created_at`, `updated_at` and `api_request_timestamp` only, so the serialization of `scheduled_start_at`/`scheduled_end_at`/`bid_due_at`/`filed_at`/`resolved_at` is PRD-silent (STEP 1b non-unique-derivability) — the instant they denote is not.
- `test_helpers/fixtures.py` — `setup_case` now refreshes `case["solicitation"]` before returning, alongside the existing `application`/`program_year` refreshes: PRD says bid submission "increases the parent solicitation's `bid_count`", so the snapshot taken at `open_solicitation` time is stale at stage `bids_placed` and later.
- `test_helpers/__init__.py` — re-export `assert_instant`.

**Fixes applied to `test_suite/`** (assertion mis-translations, STEP 2 — all made the tests more faithful, none weakened)
- `test_03_property_inspections_and_compliance.py::TestInspectionWindows::test_a_window_that_begins_when_another_ends_is_accepted` — 3 exact-string timestamp comparisons → `assert_instant`.
- `test_08_contractor_standing_cascades.py::TestReinstatementRestoration::test_reinstatement_restores_the_census_and_the_ranks_without_drift` — `bid_due_at` → `assert_instant`.
- `test_10_state_transition_corners.py::TestBiddingCycle::test_a_failed_solicitation_reopens_with_a_fresh_cutoff` — `bid_due_at` → `assert_instant`.
- `test_15_access_and_consistency_corners.py::TestCumulativeComplaintThreshold` — `filed_at` / `resolved_at` → `assert_instant`; and `test_the_third_open_complaint_is_the_one_that_demotes_the_firm` restructured to file each complaint *inside* the score-walk loop (new `_file_complaint` helper). It previously filed all three complaints up front and then asserted the 1→2→3 open-count / 85→65→45 score / APPROVED→PROBATION walk after the fact, which is unobservable because `open_complaint_count` and `performance_score` are live-computed; the walk is now checked step by step, including the demotion on the third filing.

**Fixes applied to `implementation/`:** none. No implementation defect was found; nothing was seeded, persisted, added or weakened.

**Orchestrator verification of the sweep artifacts (per known Step 7 failure mode of claiming an unbacked clean sweep):** independently read all 8 `workspace/implementation/results.{1..8}.json` (all present, ~42.8 KB each, all timestamped 06:34); each reports `passed=130 total=130 failed=0 errors=0`. Confirmed.

**Step 8 skip-condition adjudication:** Step 7 ran 3 iterations with 0 deletions and 0 `implementation/` fixes, but non-zero `test_suite/` and `test_helpers/` fixes, so the skip condition ("0 deletions AND 0 test_suite fixes AND 0 test_helpers fixes AND 0 implementation fixes") is NOT met — Step 8 runs. Its `<step_7_diff>` is dominated by timestamp-serialization silence (PRD pins the 3-fractional-digit format only for `created_at`/`updated_at`/`api_request_timestamp`) and by the live-computed vs stored distinction for `bid_count`, `open_complaint_count` and `performance_score`; those are genuine PRD silences the implementation already resolved, which is exactly what Step 8 exists to pin.

## Step 8: Finalize PRD — 2026-09-03T06:48:00.186Z

`workspace/PRD_FINALIZED.md` is written. Only one of the Step 7 items turned out to be a genuine PRD silence; the rest were test-layer defects that PRD already determines.

## Line counts
- `PRD.md`: 500 lines
- `PRD_FINALIZED.md`: 502 lines (+2, +0.4%)

## Changes
- **§2.5 Common Record Properties — insert** — one new paragraph pinning that every timestamp-valued or date-valued resource field (not just `created_at`/`updated_at`) is rendered in the same ISO 8601 UTC form with three fractional digits and a trailing `Z`, normalized to UTC from whatever offset/precision was supplied, with a bare calendar date read as that date's midnight UTC and echoed back as a full instant — `implementation/services/serializers.py:10-11,73,83,96-97,132,151,172,194-196,220-221,230,253,284-289` via `implementation/clock.py:74-80`.

## Pre-edit search log

**Edit 1 — subject: the wire rendering of timestamp/date-valued fields.**

(b) Paths enumerated and read/grepped:
- `implementation/clock.py:74-80` (`iso()`, the single renderer: `astimezone(utc)` + `%Y-%m-%dT%H:%M:%S` + `.%03dZ`; returns `None` for `None`).
- `implementation/clock.py:38-71` (`parse_datetime`, the single input normalizer: strips `Z`, accepts offsets, date-only and several fallback patterns, treats naive as UTC, converts to UTC).
- `implementation/validation.py:130-138` (`field_datetime`, the only body-timestamp entry point).
- All 13 projections in `implementation/services/serializers.py` — confirmed every one of `created_at`, `updated_at`, `deed_recorded_date`, `warranty_expires_at` (application **and** complaint), `scheduled_start_at`, `scheduled_end_at`, `insurance_expires_on`, `bid_due_at`, `proposed_start_date`, `proposed_end_date`, `submitted_at`, `lien_recorded_at`, `forgiveness_start_date`, `recapture_event_date`, `paid_at`, `filed_at`, `remedy_deadline_at`, `resolved_at` goes through `clock.iso`; `change_order` exposes none; `work_item` exposes only `created_at`.
- Grepped every `field_datetime` / `clock.iso` / `clock.now()` callsite across `routes/` and `services/` to prove no route echoes a raw client string: producers are `clock.now()` (`submitted_at`, `filed_at`, `remedy_deadline_at`, `resolved_at`, `paid_at`, `lien_recorded_at`, `created_at`/`updated_at` via `db.py:36,50`) or parsed datetimes (`bid_due_at`/`new_bid_due_at`, `scheduled_*`, `insurance_expires_on`, `deed_recorded_date`, `proposed_*`, `completion_date`→`forgiveness_start_date`, `recapture_event_date`), plus derived values from `clock.add_days`/`add_months`.
- Off-site parallel paths checked for consistency: `response.py:20` (`api_request_timestamp`, same renderer, already pinned by §2.2) and `routes/clock_routes.py:20` (the `now` echo, same renderer) — deliberately left unmentioned so the new sentence stays scoped to resource fields it accurately covers.

(c) Wording adjustments: scoped the claim to "field a resource exposes" (so it makes no claim about the `_clock` echo or `meta`), used "among them" rather than a closed list so no field is accidentally excluded, and phrased date-only handling as read-then-echo rather than asserting anything about accepted input formats generally.

Not patched (traced to Step 7 but PRD already determines them):
- `test_helpers/fixtures.py` solicitation refresh — §3.5 already states bid submission increases the parent solicitation's `bid_count` and bumps its `version`; `routes/solicitations.py:337-338` matches exactly. Pure fixture staleness.
- `test_15` complaint-walk restructure — §3.9's recompute triggers (file/resolve/sanction/close-out) make the live derivation in `services/domain.py:143-198` behaviorally indistinguishable from a stored one on every reachable path; the old test's after-the-fact walk was unobservable under any conforming implementation.

**Orchestrator check:** `PRD_FINALIZED.md` present at 502 lines vs `PRD.md` 500 — a +2-line minimal diff, consistent with the single reported insert.

## Step 9: Complete PRD — 2026-09-03T07:27:10.892Z

**Orchestrator decision (recorded per the autonomy instruction):** Step 9 was run as **three sequential file-partitioned passes** over a single `PRD_COMPLETED.md` rather than one monolithic subagent. Rationale: the implementation is ~4,100 lines across 26 files, and a single-pass full-impl scan at this size reliably under-covers — the known failure mode is a subagent that copies `PRD_FINALIZED.md` and returns a byte-identical `PRD_COMPLETED.md` having never really scanned. Passes were partitioned by implementation area, ran strictly sequentially (they edit the same file), and each later pass was told the file already existed and must not be recreated or reverted. Pass 1 = cross-cutting infrastructure (`app.py`, `middleware.py`, `validation.py`, `response.py`, `paging.py`, `errors.py`, `clock.py`, `db.py`) + `routes/{clock_routes,program_years,applicants,applications,inspections}.py`. Pass 2 = `routes/{write_ups,contractors,solicitations}.py`. Pass 3 = `routes/{loans,draw_requests,change_orders,complaints}.py` + `services/{calc,domain,serializers,constants}.py`, plus one item pass 1 explicitly handed forward (the `DRAW`-result → draw-status cascade no-ops in `routes/inspections.py:123-131`, whose PRD subject lives in §3.7).

### Pass 1 — infrastructure + intake/inspections

- PRD_FINALIZED.md 502 lines / 94,108 chars → PRD_COMPLETED.md 503 lines / 100,113 chars (+6,005 chars; 24 lines revised, 1 inserted)
- Ambiguity-pins: 21 · Mismatch-revisions: 4 · Step 8's §2.5 timestamp paragraph byte-identical and untouched

Changes: §2.1 insert (missing/empty `X-User-ID` is not itself rejected; acts under an empty identity that fails ownership comparisons — `middleware.py:38`); §2.1 revise/mismatch (dropped `WorkWriteUp` from the transitively ownership-scoped list — `routes/write_ups.py:19` makes no `scope_*` call); §2.2 insert (`api_request_id` = `req_` + 20 upper-case-alnum — `response.py:14`); §2.2 insert (`api_request_timestamp` reads the logical clock, so it repeats while the clock is still — `response.py:20`); §2.2 insert (unrouted path → 404 `ERR_NOT_FOUND`, undeclared method → 405 `ERR_METHOD_NOT_ALLOWED`, neither in the §5 catalogue — `app.py:67-79`); §2.3 insert (non-integer `limit`/`offset` → `ERR_INVALID_REQUEST`; empty value = omitted — `validation.py:168-180`); §2.3 insert (`created_at` ties broken by ascending creation sequence — `db.py:55-57`); §2.4 insert (filter semantics: empty = omitted, non-member enum / non-integer → 400, booleans accept `true|false|1|0` any case, id filters never resolved — `validation.py:183-218`); §2.4 insert (body FK absent/null/non-string → `ERR_INVALID_REQUEST`, not 404 — `validation.py:39-51`); §2.5 insert (`updated_at` == `created_at` until first mutation — `db.py:34-45`); §2.6 insert (clock endpoint returns `data` carrying only `now`; clock may move backwards; sub-ms precision held but rendered truncated — `routes/clock_routes.py:20`, `clock.py:74-80`); §2.9 revise/mismatch (three money figures at creation, not four — `routes/program_years.py:24-27`); §2.11 r3 insert (contractor body-scope comparison runs only when the body carries `contractor_id` — `middleware.py:109-119`); §2.11 r6 insert (strict typing: explicit `null` == omitted; int fields reject bools and `5.0`; bool fields reject `0`/`1`; enums case-sensitive; strings non-empty after trimming but stored untrimmed; non-object body → 400; unparseable body = `{}`; undeclared keys ignored — `validation.py:18-127`); §2.11 r9 revise/mismatch (gate is "has left `APPLIED`", not "equals `INCOME_VERIFIED`"; an `INELIGIBLE` household passes r9 and is stopped at r31 — `routes/applications.py:55-58`); §3.1 insert ×3 (duplicate `fiscal_year` → 400 `ERR_INVALID_REQUEST` — `routes/program_years.py:29-31`; duplicate `email` → `ERR_INVALID_REQUEST` — `routes/applicants.py:53-55`; certification once-only, past `APPLIED` either outcome → `ERR_INVALID_STATE` — `routes/applicants.py:124-125`); §3.2 insert (no further intake uniqueness — multiple cases per household and per dwelling allowed — `routes/applications.py:30-92`); §3.2 revise/mismatch (`deed_recorded_date` stored in the REJECTED branch too — `routes/applications.py:114`); §3.2 insert ×4 (ownership examination only from `INTAKE` — `:105-106`; inspector-identity mismatch on record-result → `ERR_INVALID_STATE`, tested after the already-recorded gate — `routes/inspections.py:92-98`; XRF reading echoed exactly — `:103`; the `INITIAL_STANDARDS` cascade fires only while the case is `OWNERSHIP_VERIFIED` and branches on deficiency count alone — `:114-119`); §3.4 insert ×2 (`risk_assessment_completed` false or posture outside `LEAD_HOLD`/`DUAL_HOLD` → 409 `ERR_INVALID_STATE` — `routes/applications.py:131-134`; SHPO determination against any other posture, incl. a repeat at `ADVERSE_EFFECT_BLOCKED` → `ERR_INVALID_STATE` — `:156-157`); §4 insert (trailing slash addresses the same endpoint — `app.py:57`).

### Pass 2 — write-ups, contractors, solicitations/bids

- 503 lines / 100,113 chars → 503 lines / 104,497 chars (+4,384; all in-paragraph, no new paragraphs or sections). Diff vs PRD_FINALIZED now touches 38 lines: pass 1's 24 preserved plus 14 new.
- Ambiguity-pins: 11 · Mismatch-revisions: 3

Changes: §3.3 insert (`expected_application_version` required, min 0, negative → `ERR_INVALID_REQUEST`; `revision_reason` optional on every revision and discarded on a first write-up; ownership is the only case gate; `revision_number` = highest used + 1 — `routes/write_ups.py:37-57`); §3.3 revise/**mismatch** (impl supersedes *every* prior `APPROVED` revision and regresses the case only when something was actually superseded **and** the case stands in `WRITEUP_APPROVED` — `:70-79`); §3.3 insert (`revision_note` required non-empty, retained off-projection, does not touch `revision_reason` — `:107,113`); §3.3 insert (the "case must be `INSPECTED`" gate raises `ERR_INVALID_STATE` ahead of the four-eyes test — `:124-129`); §3.5 insert (duplicate `license_number` → 400; `insurance_expires_on` required and may be past; neither it nor `historic_qualified` gates anything — `routes/contractors.py:37-43`); §3.5 revise/**mismatch** (opening the solicitation raises `ERR_INVALID_STATE` for three ordered gates — case `WRITEUP_APPROVED`, write-up belongs to case, write-up `APPROVED` — with the priority-repair test last; `bid_due_at` may be in the past — `routes/solicitations.py:39-51`); §3.5 insert (neither solicitation `status` nor firm standing gates bid submission — `:310-319`); §3.5 insert (tabulation runs only from `OPEN` and does not wait for `bid_due_at` — `:88-91`); §3.5 insert (shared `created_at` broken by the §2.3 creation sequence; a bid classified non-responsive has any prior `rank` cleared — `services/calc.py:155`, `routes/solicitations.py:107`); §3.5 insert (reopen `new_bid_due_at` at/before the clock → `ERR_INVALID_STATE`, tested after the `FAILED` check; no reopen cap — `:224-230`); §3.5 revise/**mismatch** (capacity is tested immediately after the `TABULATED` check, ahead of responsiveness/approved-list/lead-cert, consistent with §2.11 priority 18 < 26–28 — `:171-178`); §3.5 insert (award touches the contractor row though `active_award_count`/`performance_score` are derived at read time; neither bid counter is recomputed at award — `:189-210`, `services/serializers.py:155-159`); §3.9 insert (standing `reason` validated but unstored; sub-threshold `PROBATION → APPROVED` → `ERR_INVALID_STATE`; `SUSPENDED → APPROVED` carries no score threshold; any undefined pairing incl. a no-op → `ERR_INVALID_STATE` — `routes/contractors.py:68-81`); §3.9 insert (a direct `SUSPENDED → REMOVED` runs the same withdrawal cascade — `:86-87`, cross-checked against `routes/complaints.py:132`).

### Pass 3 — loans, draws, change orders, complaints, services (final pass)

- 503 lines / 104,497 chars → 503 lines / 111,302 chars (+6,805; every edit in-paragraph)
- 27 Edit operations, 41 behaviours pinned: **37 ambiguity-pins, 4 mismatch-revisions**. Sections touched: §2.7, §3.6, §3.7, §3.8, §3.9 (complaint/warranty prose only); passes 1–2 territory left byte-identical, §2.5 timestamp paragraph intact at line 117.

Changes — §2.7 insert ("half up" = half away from zero, and the only signed quantity it can bite, negative cumulative change-order exposure — `services/calc.py:23,208`). §3.6: `lien_position` required integer ≥ 1, zero/negative → `ERR_INVALID_REQUEST` (`routes/loans.py:145`); `recorded_instrument_number` required and validated but never stored and absent from the projection (`:146`). §3.7: draw creation compares `contractor_id` to `awarded_contractor_id` after FK resolution and before remaining payload validation, refusing with `ERR_OWNERSHIP_MISMATCH` (`routes/draw_requests.py:52`); an accepted draw touches no other row, no cap on draw count or on how many may be final (`:62`); the `DRAW` cascade keys on `draw_request_id` alone, the visit's `application_id` need not match (`routes/inspections.py:123`); **pass-1 hand-over** — `FAIL` on a draw already `INSPECTION_FAILED`, and either result against `INSPECTION_PASSED`/`APPROVED`/`PAID`, leave the draw row untouched with no `version` bump while the inspection still completes (`:126`); the four approval gates fire in §2.11 order — posture, draw inspection state, four-eyes, contract balance (`routes/draw_requests.py:88`); four-eyes uses the *most recently created* passing `DRAW` visit (`:24`); approval touches neither loan nor program year and imposes no loan-status gate (`:110`); **mismatch** — the identity `contract_earned + lien_fee = disbursed + retainage_held` is not universal, it breaks when retainage posts between a final draw's approval and its payment, so the condition is now stated (`:142`); `expected_loan_version` required integer ≥ 0 (`routes/change_orders.py:31`); `supersedes_change_order_id` resolved for existence only, not required same-loan or `APPROVED` (`:28`); denial `reason` required, validated, unstored, unprojected (`:146`); denial touches no other row (`:151`); denial has no loan-status gate (`:139`); `SUPERSEDED` is terminal alongside `DENIED`/`APPROVED` (`:71`); **mismatch** — approval runs allocation (priority 21) *before* the cumulative limit (23), so a doubly-failing approval reports `ERR_ALLOCATION_INSUFFICIENT` (`:104`); the supersedes closure is transitive across the whole store, following links belonging to other loans (`services/calc.py:193`); the 20.00 % ceiling compares the *rounded* `cumulative_delta_pct`, so 20.004 % is approved (`:228`); the lead re-hold writes the case row unconditionally, bumping `version` even at `LEAD_HOLD` (`routes/change_orders.py:130`); close-out's three gates apply in order and a `completion_date` earlier than `lien_recorded_at` is `ERR_INVALID_STATE` (`routes/loans.py:191`); the program-year row is touched at close-out only when the released amount is non-zero (`:226`, `services/domain.py:119`); the awarded firm's row is touched at close-out with no automatic standing change evaluated (`:221`); `warranty_expires_at` uses the same calendar-month arithmetic as the §3.8 forgiveness clock (`:216`, `clock.py:87`). §3.8: payment against a non-`SERVICING` note → `ERR_INVALID_STATE` (`routes/loans.py:240`); `amount_cents` may be zero (`:237`); `payment_date` required/validated but unstored and unprojected (`:238`); `unforgiven_balance_cents` floored at zero so an overpayment is accepted (`:32`); the loan `version` advances on every posting incl. zero-amount, while the program year is touched only when its ledger moves (`:249`, `services/domain.py:119`); a month counts whole when the start day-of-month recurs, clamped to a shorter month's last day, 31st → 28 Feb (`clock.py:87,95`); `sale_price_cents`/`closing_costs_cents`/`homeowner_investment_cents` optional, default zero, accepted-but-ignored on the three non-`SALE` event types (`:265`); **mismatch** — the settlement identity does not hold across *every* settlement, it fails when forgiveness plus repayments exceed principal, so the claim is scoped and the exception described (`services/calc.py:260`, `routes/loans.py:294`); a `FORGIVEN` settlement leaves the program-year row untouched (`:297`). §3.9 (complaints/warranty only): **mismatch** — filing is not ownership-scoped, `X-User-ID` is never compared to `applicant_id` (`routes/complaints.py:23`); the named `contractor_id` is resolved for existence only and need not be the case's awarded firm (`:27`); filing always moves the open-complaint count so the firm's row is touched and `version` advances on every filing, demotion or not (`:61`, `services/domain.py:189`); `resolution_note` validated when present, unstored, unprojected (`:85`); escalation leaves the open-complaint count and `performance_score` unchanged and does not touch the firm's row (`:100`, `services/domain.py:143`); `sanction_note` likewise (`:117`); a sanction writes `approved_list_status` outright without consulting current standing and without reference to the direct standing endpoint's transition table, so `PROBATION` after a `REMOVAL` does return a removed firm to `PROBATION` (`:130`).

**Pass 3 final document-integrity verification:** 503 lines / 111,302 chars, ends with a newline on the complete table row `| ERR_APPLICANT_OVER_INCOME | 422 |` — no truncation. All five top-level sections present (§1 line 3, §2 line 13, §3 line 207, §4 line 382, §5 line 456) with all 20 subsections (§2.1–§2.11, §3.1–§3.9) in order. §4 = 65 endpoint rows, §5 = 42 error rows (both match). No duplicated paragraphs from the sequential editing — the only repeated non-blank lines are 8 JSON code-fence boilerplate lines inside the two §2.2 examples; code fences balanced (4). Pass 1's §2.5 timestamp paragraph present and unmodified at line 117. No `TODO`/`TBD`/`FIXME`/conflict markers/pass comments left behind.

**Pass 3 deliberate non-pins (unreachable behavior, recorded so the record is complete):** the draw-approval posture gate's apparent divergence from §2.11 rule 11 (post-lien postures can only be `CLEAR`/`CLEARED_WITH_PROTOCOL`/`LEAD_HOLD`, so pass 1's §3.4 wording is already exact), `_awarded_bid_of`'s first-`AWARDED`-solicitation tie-break, and a zero `net_payment_cents`. Grep confirmed `AWARDED → UNDER_CONSTRUCTION` via `record_lien` is the only transition out of `AWARDED`, which is what makes §3.6's "all three rows advance their `version` by one" and close-out's unconditional `CLOSED` write safe as already written.

**Orchestrator verification of Step 9 (guarding the known no-op failure mode):** independently checked on disk — `PRD.md` 500 lines / 93,354 chars, `PRD_FINALIZED.md` 502 / 94,108, `PRD_COMPLETED.md` 503 / 111,302. `cmp` against `PRD_FINALIZED.md` reports the files **differ**, and `diff` shows **119 changed lines** — so the scan genuinely ran and did not return a byte-identical copy. Tail ends on a complete §5 table row. Pipeline complete: Step 9 has written `workspace/PRD_COMPLETED.md`.
