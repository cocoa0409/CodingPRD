# Worklog — task_1581_campus_community_basic_needs_hub

Scenario: Campus & Community Basic Needs Hub (college basic needs center): student/resident eligibility & confidential intake, pantry inventory & visit frequency limits, benefits screening (SNAP/childcare/housing) & application assistance, emergency grant application & rapid disbursement, housing insecurity referral & short-term shelter coordination, partner agency network & warm handoff, usage data & outcome tracking, stigma reduction & outreach programming

## Step 1: Create Task Directory — 2026-08-13T23:09:00.000Z

Task directory `tasks/task_1581_campus_community_basic_needs_hub/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE per instructions; no index scan performed, no other task directory touched.

## Step 2: Generate Scaffold — 2026-08-14T00:00:30.000Z

All three scaffold artifacts are generated and validated. Final lint verdict, verbatim:

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_1581_campus_community_basic_needs_hub/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_1581_campus_community_basic_needs_hub/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_1581_campus_community_basic_needs_hub/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    86
  §1.1 entities declared:     15
  §1.8 instances scanned:     18
  §1.9 instances scanned:     48
  Calls scanned (§1.8+§1.9):  819

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Deliverables** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1581_campus_community_basic_needs_hub/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design:` key
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design:` key

**Summary counts:**
- Entities: **15** (Client, StaffMember, IntakeAssessment, PantryItem, PantryVisit, VisitLineItem, BenefitsScreening, EmergencyGrantApplication, GrantFund, ShelterBed, ShelterStay, PartnerAgency, Referral, OutreachEvent, EventRegistration)
- State machines: **12** (68 transitions; cycles on grant resubmission, assessment revision, fund OPEN↔EXHAUSTED, event OPEN↔FULL, client ACTIVE↔SUSPENDED, referral EXPIRED→SENT, registration CANCELLED→REGISTERED)
- Calculations: **12** (incl. pinned-order SNAP benefit rounding, tiered poverty-table eligibility with HOMELESS override, weighted screening score with zero-gates/ceiling, dual-basis fund remaining and pantry points, 168h frequency window, award sizing min-of-4-caps, CRISIS-overflow referral capacity, counselor selector)
- Validations: **25** (ordered priorities; auth → role → existence → ownership → confidentiality wall → state → OCC → safety/SoD → temporal → constraint → uniqueness → referential → fiscal)
- Endpoints: **86** (incl. `/_clock/set_current_utc` with pinned default 2026-08-01T00:00:00Z and `/_sweeps/run_pending_transitions` ops checkpoint)
- Errors: **51** (all referenced by validations/transitions/concurrency rules and exercised in the design files)
- Roles: **9** (Anonymous+HubAdmin opaque; Client/StaffMember/PartnerAgency entity-backed; segregation-of-duties on grant review and two-person disburse rule)
- Difficulty design instances: **18** (9 rules × 2, each with structured `setup_api_calls`/`trigger` chains and precomputed literal asserts — e.g., SNAP estimate 19205 vs 19206 rounding divergence, 1.2996/1.3004 band straddle, depth-4 grant-expiry→fund-reopen→queue-promotion cascade, PET-bed sanitation buffer vs client night-set overlap semantics)
- Corner design instances: **48 active + 3 excluded-because stubs** across all nine claim-extraction-guide sections

Additional audits passed: placeholder closure (zero unbound `${var}`), grounds resolvability, forbidden-vocabulary scan, error-code coverage, cross-file name uniqueness, and end-state replay of every setup chain.

## Step 3: Copy Shared Files — 2026-08-14T00:02:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1581_campus_community_basic_needs_hub/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-14T00:25:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1581_campus_community_basic_needs_hub/workspace/PRD.md` — 396 lines, ~10,200 words. The withheld design files were not opened.

## Section list

- **1. Introduction** (2 paragraphs — confidentiality/stigma-reduction framing + technical posture)
- **2. Global Specifications** — 2.1 Roles & identity resolution (9 roles, entity-backed vs opaque prose per role); 2.2 API Response Structure (byte-verbatim fixed block, diff-verified); 2.3 Pagination (limit 10/1/100, offset 0, created_at ascending); 2.4 Logical clock (startup `2026-08-01T00:00:00Z`, forward-only) + sweep checkpoint (pinned 5-type order, 6 output counters); 2.5 Common resource properties (incl. VisitLineItem carrying only `id`/`created_at`); 2.6 Request validation cascade (10-step priority ordering with worked examples); 2.7 Money/points/precision conventions; 2.8 OCC (all three rules, `ERR_STALE_VERSION`/412 each); 2.9 Confidentiality wall + two SoD joints; 2.10 Derived fields & automatic posture flips
- **3. Business Logic** (9 subsections) — 3.1 staff bootstrap & client registration/lifecycle (suspend/reinstate/exit unwind); 3.2 intake assessment lifecycle (eligibility band, poverty table, risk tier, points allotment); 3.3 pantry catalog & points economy (168h frequency, line pinning, checkout reserved-basis admission, void reversal); 3.4 screenings (counselor selector, weighted score, pinned 7-step SNAP estimate); 3.5 grants & fund accounting (dual bases with worked 500000/100000/50000 example, 4-cap award sizing, 72h disbursement, queued promotion); 3.6 shelter beds/stays (half-open bed rule vs closed night-set client rule, PET buffer, no-show restriction); 3.7 agencies & referrals (capacity + CRISIS overflow, 120h SLA, resend); 3.8 outreach events & registrations; 3.9 usage summary (all 9 metrics)
- **4. Endpoint Definitions** — 86 rows, 4 columns, roles verified cell-by-cell against scaffold
- **5. Error Code Catalogue** — 51 rows, 2 columns, statuses verified against scaffold

## Zero-Silence coverage audit (mechanical, scaffold-parsed)

- **Field names**: 127 required identifiers (96 entity fields + request bodies + query params + path params), 0 missing in backticks — PASS
- **States**: all state-machine states present as exact UPPERCASE strings, 0 missing (after fixing `DISCARDED`, which initially appeared only as a lowercase verb) — PASS
- **Enum values**: all field-level enum members + bed features + service categories present — PASS
- **Roles**: 9/9 named with exact spelling — PASS
- **Errors**: 51/51 error IDs appear in §2/§3 prose with trigger conditions (§5 carries no conditions) — PASS
- **§3 path purity**: 791 backticked tokens scanned in §3, zero path/method/combo violations — PASS
- **§2.2 verbatim**: byte-identical to the fixed source block — PASS
- **Rule coverage (Contract 2, manual walk)**: validation priority cascade expressed as ordered 10-step list; 3/3 OCC rules with endpoint + `expected_*_version` + error id + 412; all ~70 state transitions named from→to with preconditions/side effects; all 12 calculations in precise prose (constants embedded, per-step rounding pinned, inclusive/exclusive boundaries stated); cross-entity cascades (exit unwind, disburse → fund counters → reopen → promotion, verify → supersede → client flip) all stated; applies_to scopes enumerated; sibling branches (withdraw/decline/cancel sets) symmetric; no pseudocode operators or fuzzy quantifiers in prose (mechanical scan clean).

## Step 5: Generate Unit Tests — 2026-08-14T01:20:00.000Z

All audits pass. Generation complete — here is the summary.

## Deliverables

**`test_helpers/` (9 files, 1769 lines)** — all under `/home/ubuntu/github/CodingPRD/tasks/task_1581_campus_community_basic_needs_hub/test_helpers/`:
- `types.py` — 16 entity TypedDicts + 16 status/role enums; `VisitLineItem` correctly carries only `id` + `created_at` (append-only, per PRD §2.5)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (60+ methods)
- `api_errors.py` — all 52 `ERR_*` ids with HTTP map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity structural assertions + `assert_fund_conservation`
- `factories.py`, `constants.py` (poverty/SNAP tables, points/cap/window constants)
- `test_users.py` — shared constants for the two opaque roles (Anonymous, HubAdmin) only; per-instance builders for all 7 entity-backed roles (prevents the ownership-rejection cascade bug)
- `fixtures.py` — 5 tiers: staff/client creators, `create_active_client` intake pipeline (captures client version for the OCC verify), pantry/agency/fund/bed/event bundles, grant pipeline shortcuts (submitted→under_review→approved→disbursed), `setup_exhausted_fund_with_queued_grant`, `setup_client_at_lifetime_cap`, `setup_disbursed_grant_scenario`
- `__init__.py` — barrel re-export

**`test_suite/` — 85 tests, 12 files + `conftest.py`** (all under `.../test_suite/`):

| File | Tests |
|---|---|
| test_01_registration_directory_and_envelope.py | 6 |
| test_02_intake_assessment_lifecycle.py | 7 |
| test_03_pantry_points_economy.py | 7 |
| test_04_pantry_visit_operations.py | 8 |
| test_05_benefits_screenings.py | 5 |
| test_06_grant_fund_accounting.py | 7 |
| test_07_grant_review_workflow.py | 10 |
| test_08_shelter_stays.py | 9 |
| test_09_referrals_and_agencies.py | 9 |
| test_10_outreach_events_and_usage_reporting.py | 5 |
| test_11_client_exit_suspension_and_confidentiality.py | 7 |
| test_12_occ_and_request_validation.py | 5 |

## Coverage

- **Queue A (Difficulty): 36 tests covering 18/18 instances, exactly 2 each** — every instance's recipe was split into two independently-runnable tests (each self-sufficient under per-test-server restart), e.g. the 168h strict-window instance splits into third-visit-rejected vs exactly-168h-admitted; the PET-buffer instance splits into plain-bed turnover vs buffer-block/buffer-expired.
- **Queue B (Corner): 49 tests covering 48/48 non-stub instances** (risk_tier_derivation got 2 tests: null→CRISIS and ELEVATED/STABLE).
- **3 `excluded_because:` stubs not translated**; all three cross-references verified to resolve to real difficulty instances.

## Skipped instances

None — every non-stub instance passed the PRD-first two-condition filter. One assertion was narrowed, not skipped: in `Corner/entities/client_create_defaults_applied`, the recipe's literal `version == 1` is not uniquely derivable (PRD §2.5 says only "an integer that starts low"), so the test asserts the derivable claims (enrolled_credits default 0, INTAKE_PENDING, risk_tier null, bare-UUID id, integer version) without pinning the start value.

## Stage 2 self-audit verdict

- [x] Every queue-A instance has ≥2 tests tagged `Design: Difficulty/<rule_id>/<name>`; every non-stub queue-B instance has ≥1 tagged `Design: Corner/<section>/<name>` — verified programmatically (85 tests, 0 untagged/dual/unknown tags, 0 stub translations)
- [x] PRD citation pass: 138 quoted segments (≥8 words each) all survive literal grep of `workspace/PRD.md`; citations are rule-bearing (error ids, thresholds, transitions), not endpoint-titular
- [x] All asserted `error_id`s and both priority orderings (client-gate-before-fund-gate via §2.6 steps 8/10; stay window-then-placement via §3.6 "Placement then checks") are named in PRD prose
- [x] No `skip`/`skipif`/`xfail` anywhere; no "scaffold" references in generated code
- [x] `pytest --collect-only` succeeds (85 tests); pyflakes clean (one real bug caught and fixed: missing `create_event_registration_payload` import in `fixtures.py`; class-helper `api`→`api_client` references corrected)
- [x] All arithmetic pre-verified against the PRD formulas (SNAP 19205 via pinned per-step rounding, ratios 1.2996/1.3004/7.1713/0.7968, HOUSING ceiling 39, floor(5×1.2)=6 overflow, 2026-08-03/08-10 are Mondays, +365d = 2027-08-01)

**Verdict: PASS.**

## Step 6: Generate Implementation — 2026-08-14T01:33:00.000Z

The implementation is complete and verified. Final summary:

## Implementation Complete: task_1581_campus_community_basic_needs_hub

### File list (all under `/home/ubuntu/github/CodingPRD/tasks/task_1581_campus_community_basic_needs_hub/workspace/implementation/`)

- `start.sh` — executable launcher (guarded pip install, `exec python3 app.py`)
- `requirements.txt` — `flask>=2.2`
- `app.py` — Flask entry point, blueprint registration, ApiError/404/500 handlers
- `db.py` — in-memory store (15 collection dicts + insertion-sequence counter; empty at boot, zero seeding)
- `errors.py` — all 51 error IDs from the scaffold catalog with exact HTTP statuses
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (9 roles), entity-backed identity resolution (Client non-EXITED, ACTIVE staff with matching `staff_role`, PartnerAgency), ownership/actor-pin/confidentiality-wall checks
- `response.py` — envelope: `meta{api_request_id, api_request_timestamp}`, `response_type`, `data`; list `meta` adds `limit/offset/total_count/has_more`
- `util.py` — logical clock (pinned default `2026-08-01T00:00:00Z`, forward-only, no auto-sweep), 3-fractional-digit timestamps, Monday week windows
- `validate.py` — body/query validators (typed ints/bools/enums/dates), pagination (limit 1–100 default 10, offset ≥ 0)
- `routes/` — 13 modules: `clock.py` (clock + sweep), `staff.py`, `clients.py` (incl. exit unwind cascade), `assessments.py` (submit/verify/return/revise + OCC), `pantry.py` (items/visits/line-items/checkout/void), `screenings.py`, `grants.py` (funds + applications), `shelter.py` (beds + stays), `agencies.py` (agencies + referrals), `events.py` (events + registrations), `reports.py`, `helpers.py`
- `services/` — `calculations.py` (all 10 calculation rules), `core.py` (record lifecycle, derived-field serializers, counter reconciliation, fund reopen/promotion, visit voiding), `sweep.py` (pinned 5-step order)

### Endpoint coverage: 86/86 (verified programmatically against the PRD §4 table; 0 missing)

### State machine coverage: all 12 machines implemented with machine-specific errors
Client (incl. auto-activate on first verify, suspend auto-void, full exit unwind), IntakeAssessment (incl. supersede, 365-day expiry with derived-field unwind, return/revise loop), PantryItem, PantryVisit (incl. COMPLETED-void stock/points restore), BenefitsScreening (incl. withdrawable pre-terminal set, band-gated assist), EmergencyGrantApplication (incl. QUEUED parking, resubmission cycle clearing `reviewed_by`, 72h disburse window), GrantFund (OPEN↔EXHAUSTED flips + reopen promotion of earliest QUEUED), ShelterStay (incl. no-show sweep and 2-strike restriction), Referral (incl. 120h SLA expiry, EXPIRED→SENT resend), PartnerAgency, OutreachEvent (OPEN↔FULL auto-flips), EventRegistration (incl. cancelled-row reactivation returning the same id).

### Calculation coverage: 10/10, all replayed against the pinned corner values
eligibility_band (163100→1.2996 FULL; HOMELESS 900000→7.1713 FULL; 163200→1.3004 PARTIAL), snap_benefit_estimate (pinned per-step rounding → 19205), screening_score (54/POSSIBLY; CHILDCARE/SNAP zero gates; HOUSING-STABLE ceiling 39), pantry_points (settled vs reserved bases converge at checkout; inclusive cap), visit_frequency_check (strict 168h edge verified at exact boundary), grant_award_sizing (four-cap min incl. lifetime-cap exhaustion → ERR_AWARD_CAP_EXHAUSTED), fund_remaining (committed vs cash bases), referral_capacity_check (CRISIS overflow floor(cap×1.2) ladder verified), risk_tier, counselor_assignment (A,B,A tie-break verified), shelter_stay_windows (PET buffer blocks turnover day; client night-set allows it), usage_summary (windowed aggregates verified).

### start.sh contract confirmation
Reads `$PORT` (default 10000), binds `0.0.0.0`, runs in the foreground via `exec python3 app.py`, dependency install guarded by `python3 -c "import flask"` so per-test reboots skip pip. Verified: fresh `bash start.sh` boots in ~2.5s on a custom port, store empty, clock at the pinned default, and a kill+relaunch carries no state over.

### Verification performed
Five smoke rounds (~200 assertions) replaying the difficulty-design and corner-design recipes end-to-end; all pinned values, error IDs, precedence orderings (ownership-before-state, state-before-fiscal, temporal-before-constraint, confidential-wall vs role), OCC flows (client/item/fund versions), and cascades (grant-expiry depth-4 promotion, referral-expiry capacity release, exit unwind) pass. The only smoke failures observed were artifacts of the ad-hoc scripts' shared mutable clock/state, each re-verified green in isolation.

## Step 7: Run Tests and Iterate — 2026-08-14T01:44:00.000Z

All 8 rounds pass 85/85. Exit condition met.

## Summary

**Iterations run:** 2 (baseline sweep → fix → confirming sweep; 8 parallel rounds each, all rounds run to completion)

**Baseline:** 80/85 in every round — the same 5 tests failed deterministically in all 8 rounds (no flakiness in the union).

**Tests deleted:** none. Every failing test traced to a verbatim PRD rule with unique derivability; all five were test-side expression bugs, fixed (not weakened) per STEP 2.

**Fixes applied to `test_helpers/`:** none — fixtures, factories, and role-header builders were all PRD-consistent.

**Fixes applied to `test_suite/`** (5 tests, 4 files):

1. `/home/ubuntu/github/CodingPRD/tasks/task_1581_campus_community_basic_needs_hub/test_suite/test_02_intake_assessment_lifecycle.py` — `test_revision_loop_return_to_draft_to_verified`: the revise payload set `household_size: 1` while leaving `dependents_under_18: 1`, so PRD §3.2's submit-time domain rule ("dependents fewer than the household size … rejected as `ERR_INVALID_REQUEST`") forced a PRD-faithful server to reject the resubmit. Added `dependents_under_18: 0` to the revise payload; the asserted recompute (ratio 0.7968, band FULL) is unchanged.
2. Same file — `TestRiskTierDerivation::test_risk_tier_materializes_at_verification`: unpacked 2 values from the 3-tuple `create_active_client` (`ValueError: too many values to unpack`). Fixed to `client, _, _ =`.
3. `/home/ubuntu/github/CodingPRD/tasks/task_1581_campus_community_basic_needs_hub/test_suite/test_03_pantry_points_economy.py` — `TestSettledVsReservedBasis::test_open_visit_reserved_basis_exceeds_settled_basis`: asserted `provisional_points == 20` on the stale check-in response snapshot (captured before the line add). Now re-fetches via `GET /pantry-visits/{vid}` before asserting; the server-side reserved-basis assertion (20) already passed.
4. `/home/ubuntu/github/CodingPRD/tasks/task_1581_campus_community_basic_needs_hub/test_suite/test_06_grant_fund_accounting.py` — `TestFundRemainingDualBasis::test_two_remaining_bases_diverge_after_approval`: asserted `remaining_cash_basis == 450000`, contradicting PRD §3.5's verbatim formula ("the allocation minus disbursed alone") — 500000 − 0 = 500000 (450000 was copied from the PRD's 100k-committed/50k-disbursed example). Corrected the constant to 500000.
5. `/home/ubuntu/github/CodingPRD/tasks/task_1581_campus_community_basic_needs_hub/test_suite/test_12_occ_and_request_validation.py` — `test_occ_assessment_verify_stale_client_version_rejected`: `stale_version` was captured from the post-verification refreshed client, so it equaled the current version and the "stale" verify legitimately succeeded (PRD §2.8 advances client version exactly at verification). Rewrote the setup to capture the client's version before the first verification, making the second verification genuinely stale → `ERR_STALE_VERSION` 412.

**Fixes applied to `implementation/`:** none — the implementation was PRD-faithful in all five cases (the failures were the tests asking it to violate PRD, or reading stale snapshots/miscomputing constants).

**Final state:** all 8 parallel rounds at 85/85 passed, confirming no timing-sensitive flakiness.

## Step 8: Finalize PRD — 2026-08-14T01:56:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1581_campus_community_basic_needs_hub/workspace/PRD_FINALIZED.md` was created via `cp` and is **byte-identical to PRD.md** — no edits were needed.

**Line counts:** PRD.md = 395 lines, PRD_FINALIZED.md = 395 lines, 0% delta (diff confirms identical).

**Why each of the 5 diff items was judged a pure test bug (no PRD silence, no impl mismatch):**

1. **`test_02` revise payload (`household_size: 1` + `dependents_under_18: 1`)** — PRD §3.2 already pins both halves of the behavior: revise "overwrite[s] the corresponding fields in place" and submit "re-validates the numeric domains above — … dependents fewer than the household size … — with violations rejected as `ERR_INVALID_REQUEST`". Implementation matches exactly: `revise_assessment` overwrites supplied fields in place and clears the frozen ratio/band (`implementation/routes/assessments.py:210-241`); `submit_assessment` calls `_validate_assessment_domains` which rejects `dep >= household_size` with `ERR_INVALID_REQUEST` (`assessments.py:48-50, 146`). The test fixture was asking the server to accept a PRD-prohibited combination.

2. **`test_02` tuple unpacking (`create_active_client`)** — The helper returns a 3-tuple `(client, assessment, client_headers)` (`test_helpers/fixtures.py:137`). Pure test-code bug with zero PRD surface; no endpoint behavior involved.

3. **`test_03` stale check-in snapshot (`provisional_points == 20`)** — PRD §3.3 already pins that a new visit starts with `points_spent` held at 0 and that "the visit's `provisional_points` grows by the same amount" on each line add; §2.5 pins that the add mutates the visit. Implementation: check-in creates the visit with `provisional_points: 0` (`implementation/routes/pantry.py:146`), line-add increments it (`pantry.py:203`), and `GET /pantry-visits/{vid}` returns current state (`pantry.py:166-172`). The test asserted against a response snapshot captured before the line add.

4. **`test_06` `remaining_cash_basis == 450000` → 500000** — PRD §3.5's formula is verbatim: "`remaining_cash_basis` is the allocation minus disbursed alone". Implementation computes exactly `allocated_cents - disbursed_cents` (`implementation/services/core.py:76`). The test had miscopied 450000 from the PRD's worked example (500k fund with 100k committed / 50k disbursed) into a scenario with 0 disbursed, where the formula yields 500000.

5. **`test_12` stale-version capture ordering** — PRD §2.8 and §3.2 both pin this explicitly: "Each verification also increments the client's `version` by one, which is precisely what makes a second verification carrying the older `expected_client_version` stale" (rejected `ERR_STALE_VERSION`, HTTP 412). Implementation: `verify_assessment` checks `expected != client["version"]` → `ERR_STALE_VERSION` (`implementation/routes/assessments.py:170-171`) and `touch(client)` increments version by one (`assessments.py:189`, `services/core.py:20-23`). The test captured the "stale" version from the post-verification refreshed client, making it equal to the current version.

**Pre-edit search log:** no edits were committed, so no per-edit logs apply; each item's implementation path was enumerated and read as listed above before concluding "no edit".

## Step 9: Complete PRD — 2026-08-14T02:15:00.000Z

All changes verified. The final summary:

## Summary

**Source vs output**: `PRD_FINALIZED.md` (395 lines, 74,514 chars) → `PRD_COMPLETED.md` (395 lines, 77,162 chars). Char-delta **+2,648**; line count unchanged — all 22 edits are in-paragraph inserts/revisions, no new sections, no new paragraphs.

**Counts**: 24 ambiguity-pins, 2 mismatch-revisions (26 changes across 20 lines).

**Changes** (section — insert|revise — ambiguity|mismatch — what changed — impl ref):

- §2.3 — insert — ambiguity — out-of-range/non-integer `limit`/`offset` rejected with `ERR_INVALID_REQUEST` — implementation/validate.py:137-159
- §2.3 — insert — ambiguity — same-instant creation timestamps ordered by insertion sequence — implementation/services/core.py:32-34 (db.py:30 `_seq`)
- §2.3 — insert — ambiguity — `total_count` is pre-pagination match count; `has_more` = offset + page size < total_count — implementation/response.py:23-34
- §2.4 — insert — ambiguity — clock set to current instant admitted; strictly earlier `to_iso8601` → `ERR_INVALID_REQUEST` — implementation/util.py:68-75
- §2.6 — insert — ambiguity — body-supplied identifiers (`fund_id`, `item_id`, `bed_id`, `agency_id`, registration `client_id`) that don't resolve → `ERR_NOT_FOUND` — implementation/validate.py:129-134
- §2.8 — insert — ambiguity — omitted/non-integer expected-version field → `ERR_INVALID_REQUEST` before comparison — implementation/routes/assessments.py:167-169, pantry.py:80-82, grants.py:231-233
- §3.1 — insert — ambiguity — negative `enrolled_credits` → `ERR_INVALID_REQUEST` — implementation/routes/clients.py:31
- §3.1 — insert — ambiguity — reinstate from non-`SUSPENDED` → `ERR_CLIENT_NOT_ACTIVE` — implementation/routes/clients.py:86-87
- §3.1 — revise — mismatch — exit cancels **all** `RESERVED` stays (PRD said "future"); impl applies no date filter — implementation/routes/clients.py:111-114
- §3.2 — insert — ambiguity — `return_notes` required on return call (missing/non-string → `ERR_INVALID_REQUEST`) — implementation/routes/assessments.py:201-203
- §3.2 — insert — ambiguity — revise does not clear `submitted_at`; next submit restamps it — implementation/routes/assessments.py:236-239
- §3.2 — insert — ambiguity — 2,160-hour no-show window inclusive at both ends (exactly-2,160h-old marking counts) — implementation/services/calculations.py:321-331
- §3.3 — insert — ambiguity — initial `quantity_on_hand` bounded at ≥ 0 — implementation/routes/pantry.py:42
- §3.3 — insert — ambiguity — config update re-applies creation-time bounds (`point_cost` ≥ 1, `reorder_threshold` ≥ 0, `per_visit_limit` ≥ 1) — implementation/routes/pantry.py:85-90
- §3.3 — insert — ambiguity — config updates and restocks admitted on `ACTIVE` or `DISCONTINUED` items — implementation/routes/pantry.py:74-107 (no state gate)
- §3.4 — insert — ambiguity — counselor tie-break: earliest `created_at`, remaining (identical-timestamp) ties by creation order — implementation/services/calculations.py:265-271
- §3.5 — revise — ambiguity — `fiscal_year` pinned as an integer label — implementation/routes/grants.py:45 (`req_int`)
- §3.5 — insert — ambiguity — application creation requires `ACTIVE` client (`ERR_CLIENT_NOT_ACTIVE`) and verified assessment (`ERR_ASSESSMENT_REQUIRED`) — implementation/routes/grants.py:104-107
- §3.5 — insert — ambiguity — `info_request_notes` required on request-info call — implementation/routes/grants.py:213
- §3.5 — insert — ambiguity — `decision_rationale` required on deny call — implementation/routes/grants.py:262
- §3.7 — insert — ambiguity — agency config updates admitted in `ACTIVE` or `PAUSED`; ≥1 floor on `weekly_capacity` still applies — implementation/routes/agencies.py:86-96
- §3.7 — insert — ambiguity — `decline_reason` required on decline call — implementation/routes/agencies.py:298
- §3.8 — insert — ambiguity — `anonymous_attendance_allowed` is advisory; registration never rejects a `display_alias` on its account — implementation/routes/events.py:116,139,146 (flag stored, never enforced)
- §3.8 — insert — ambiguity — reactivation refreshes the row's `display_alias` from the new payload (defaulting to `alias_name`) — implementation/routes/events.py:138-141
- §3.8 + §4 — revise — mismatch — reactivated registration returns `201 Created` (PRD §4's modify→200 blanket rule would have implied 200); §4 carries the carve-out — implementation/routes/events.py:150
- §3.9 — insert — ambiguity — unparseable `from_date`/`to_date` bound → `ERR_INVALID_REQUEST` — implementation/routes/reports.py:19-25

All other impl behaviors (endpoint/role matrix, state machines, calculation formulas incl. pinned SNAP/screening rounding, sweep order and boundaries, OCC cascade positions, error catalogue, envelope shape, confidential-wall cascade position) were already uniquely pinned by the PRD and required no change.
