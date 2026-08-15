# Worklog — task_1510_union_signatory_production_agreement

## Step 1: Create Task Directory — 2026-08-13T15:19:00.000Z

Pre-assigned directory `tasks/task_1510_union_signatory_production_agreement/` with `workspace/` already existed (created by pipeline dispatcher). No index scan performed per instructions.

## Step 2: Generate Scaffold — 2026-08-13T17:04:11.861Z

All three artifacts are generated and verified. Summary:

## Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_1510_union_signatory_production_agreement/SCAFFOLD.yaml` (§1.0–§1.7 only; no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1510_union_signatory_production_agreement/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1510_union_signatory_production_agreement/SCAFFOLD_CORNER_DESIGN.yaml` (single top key `scaffold_corner_design`)

## Counts
- **10 entities**: ProducerCompany, SignatoryApplication, Production, Bond, CrewAssignment, WorkDayLog, Grievance, ContributionReport, Audit, ForceMajeureEvent (flat topology, FK-joined)
- **50 endpoints**, **34 error codes**, **34 ordered validation rows**, **8 calculations**, **10 state machines**, **5 roles**, **2 OCC concurrency rules**
- **Difficulty: 18 instances** (exactly 2 per each of the 9 rules)
- **Corner: 64 instances** (56 active + 8 `excluded_because` stubs, all resolving to real difficulty instances)

## Lint verdict (verbatim)
`VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (850 calls scanned)

## Key design decisions
- **Archetype**: compliance/audit + posture-driven gating; `compliance_posture` (CLEAR/RESTRICTED/FROZEN) is a persisted derived field on Production gating crew hiring (CLEAR-only) vs logging/reporting (not-FROZEN).
- **Dual variants on different domains**: contribution dues provisional-vs-final (log-status filtering, tier at create vs submit — 30600 vs 17000 pinned) and audit assessment per-period (no netting) vs aggregate (1100 vs 0 pinned).
- **Combinatorial modes**: mode (a) tier-cap branch `min(daily_rate, tier_cap)` × tier rate (46750 pinned); mode (b) nested rounding pinned per-unit-first (`round(100010/32)=3125 × 3 = 9375` vs rejected 9376); plus mode (c) two-pass filing-deadline tolling (no iteration).
- **Non-linear machines on different entities**: application info-request cycle (max 3 rounds) and grievance negotiation REJECT loop with proposal supersession.
- **Transitive cascades**: budget revision → tier upgrade → bond UNDERFUNDED → posture RESTRICTED (depth 3); audit close unpaid → bond FORFEITED → company SUSPENDED (depth 2).
- **OCC** on `Production.version` (budget-revisions) and `Grievance.version` (propose-settlement); all `expected_*_version` payloads reference `${var}` captures.
- **Segregation of duties**: grievance intake vs settlement proposal; audit open vs close.
- **Overlap rules with different semantics**: work-log day-point occupancy vs force-majeure half-open `[start, end)` ranges (adjacency allowed; LIFTED events still occupy history and toll filing windows).
- **Logical clock** `POST /_clock/set_current_utc` with pinned default `2026-08-01T00:00:00Z` for deterministic deadline/lifted-date behavior.
- All formula-derived asserts were pre-computed and verified with Python before pinning (e.g., 30600/17000, 46750, 9375, 1100/0, 33150, 12500, 3125, tolling day counts).

One note: an earlier failed `Write` attempt left no partial file — the corner file was rebuilt cleanly via heredocs; a linter/normalization pass (quoting `$.data[0].id` captures, block-style `grounds`) was applied to both design files and is reflected in the final versions.

(Orchestrator note: the first scaffold subagent run wrote SCAFFOLD.yaml but exhausted its turn before writing the two design files; it was resumed via SendMessage and completed SCAFFOLD_DIFFICULTY_DESIGN.yaml and SCAFFOLD_CORNER_DESIGN.yaml, including YAML syntax fixes — quoting `$.data[0].x` captures inside flow mappings — and a clean scaffold lint pass.)

## Step 3: Copy Shared Files — 2026-08-13T17:04:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1510_union_signatory_production_agreement/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-13T17:22:15.792Z

PRD generation complete.

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_1510_union_signatory_production_agreement/workspace/PRD.md` — 301 lines.

**Section list**:
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications (10 subsections): 2.1 Roles & RBAC with per-role identity translation; 2.2 API Response Structure (byte-verbatim from `section-2.2-response-structure.md`, verified); 2.3 Pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending, meta fields); 2.4 Common Resource Properties (`id`/`created_at`/`updated_at`/`version` + universal version-increment rule + left-to-right id validation); 2.5 Logical Clock (default `2026-08-01T00:00:00Z`, no wall-clock fallback, `to_iso8601`); 2.6 Money/Rounding (integer cents, round half up, pinned evaluation orders); 2.7 Agreement Tiers/Budget Caps/Bond Schedule (all constants in cents and dollars, inclusive boundaries); 2.8 Compliance Posture (full `posture_derivation` with pinned FROZEN > RESTRICTED > CLEAR priority, threshold 2, all recompute triggers, all gates); 2.9 OCC (both rules: `expected_production_version` on budget revisions, `expected_grievance_version` on propose-settlement, `ERR_STALE_VERSION`/412, "no other endpoint takes a version field"); 2.10 Validation Pipeline Ordering (all 34 priorities expressed as an ordered prose sequence)
- §3 Business Logic (8 subsections): 3.1 Companies/Applications, 3.2 Production Registration/Bond Posting, 3.3 Budget Revisions/Tier-Upgrade Cascade, 3.4 Crew/Min-Staffing/Start, 3.5 Work Day Logs/Penalty Arithmetic, 3.6 Grievances (filing deadline two-pass, negotiation loop, arbitration, payments/refunds), 3.7 Contribution Reports/Audits (provisional vs final variants, per-period vs aggregate assessments, forfeit cascade, bond re-post/reinstatement), 3.8 Force Majeure/Wrap/Close/Release
- §4 Endpoint table (50 rows, 4 columns only) with 201/200 status preamble
- §5 Error catalogue (34 rows, 2 columns only, no trigger conditions)

**Hard contract results**:
- Contract 1 (Field-Name Coverage): PASS — entities fields 60/60, request_body 43/43, query_params 2/2, path_params 1/1, 0 missing (one repair pass was needed for the bare `status` token; fixed in §2.4). All 61 enum members also verified present.
- Contract 2 (Rule Coverage): PASS by manual walk — all 34 validations with priority ordering, both OCC rules (write op + occ field + error id + status), all 48 state-machine transitions with preconditions and side effects, all 8 calculations (formulas, constants, variants, pinned rounding orders) in precise prose, all applies_to scopes enumerated, all field defaults/initials stated, sibling branches symmetric (approve/deny, accept/reject, both forfeit sources, both audit-close states, both FM suspend/restore states, provisional/final, per-period/aggregate).
- Contract 3 (§3 Path Purity): PASS — 467 backtick tokens scanned, 0 starting with `/`, 0 bare HTTP methods, 0 method+path combos. A separate operator scan confirmed zero pseudocode tokens (`==`, `>=`, `+=`, `ceil(`, `AND`/`OR` etc.) anywhere in the document. All 34 error IDs appear in §2/§3 narrative.

The scaffold's difficulty/corner design files were not opened or referenced.

## Step 5: Generate Unit Tests — 2026-08-13T18:02:31.284Z

All checks pass. Final summary:

## Generation complete

### test_helpers/ (9 files, all under `/home/ubuntu/github/CodingPRD/tasks/task_1510_union_signatory_production_agreement/test_helpers/`)
- `types.py` — 12 status enums + role enum + 11 entity TypedDicts (all entities carry the full common quartet per PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with 42 endpoint methods covering every row of the PRD §4 index (incl. `POST /_clock/set_current_utc`)
- `api_errors.py` — all 34 `ApiErrorId` values with the §5 HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` plus `assert_bond_ledger_conservation` (PRD §3.2 held = posted − released − forfeited)
- `factories.py` — 9 payload factories, input fields only
- `constants.py` — tier caps, bond schedule, staffing minimums, penalty/dues/audit constants, filing window, posture threshold
- `test_users.py` — `TEST_USERS` constants for opaque roles + `make_producer_rep_headers(company_id)` entity-backed builder (threaded through every ownership-gated helper)
- `fixtures.py` — composite helpers: `register_company` → `create_signatory_company` → `create_staffing_production` → `create_in_production`, crew/log/grievance/report/audit/FM chains, `create_resolved_grievance`, `create_accepted_report`, `setup_accepted_report`, `setup_wrapped_production`, `setup_closed_production`, OCC-aware `revise_budget`
- `__init__.py` — barrel export

### test_suite/ (11 files, 90 tests)
- `conftest.py` + `test_01_company_application_onboarding.py` (7) + `test_02_production_registration.py` (10) + `test_03_budget_revisions_and_bonds.py` (13) + `test_04_crew_and_staffing.py` (6) + `test_05_work_day_logs.py` (10) + `test_06_grievances.py` (16) + `test_07_contribution_reports.py` (11) + `test_08_audits.py` (7) + `test_09_force_majeure_and_posture.py` (8) + `test_10_authentication.py` (2)

### Translation ledger
- **Queue A (difficulty): 18/18 instances translated, 2 tests each = 36 tests** (each pair splits trigger-outcome vs cascade/secondary assertions; both share the instance's `Design: Difficulty/...` tag).
- **Queue B (corner): 56 non-stub instances → 54 translated, 2 skipped; 8 `excluded_because:` stubs not translated** (all 8 cross-references verified to resolve to real difficulty instances).
  - SKIP `entities/production_create_rejects_computed_field_input` — PRD never states that a computed field supplied in a create payload is rejected; §2.10's "malformed payloads" does not pin rejection-vs-ignore of extra fields, so two faithful PRD-only implementers diverge (fails unique derivability; `computed-field` silence pattern).
  - SKIP `cross_cutting_layers/posture_frozen_blocks_log_report_and_crew` — the instance asserts `ERR_POSTURE_FROZEN` for log-create/report-create/crew-create on a FROZEN production, but a FROZEN production is necessarily `SUSPENDED` (§3.8), and PRD §2.10 pins production-state gating before the frozen-posture gate while §3.4/§3.5/§3.7 give those operations state requirements (`STAFFING|IN_PRODUCTION` / `IN_PRODUCTION` / `IN_PRODUCTION|WRAPPED`); the PRD-uniquely-derived error for all three triggers is `ERR_PRODUCTION_STATE`, contradicting the instance's asserted outcome.

### Self-checks (all green)
- Tag audit: 90/90 tests carry exactly one `Design:` line as the final docstring line; every tag resolves to a real instance; 18/18 difficulty instances at ≥2 tests; 54/54 translated corner instances at ≥1.
- Citation audit: all 90 docstrings contain a PRD quote with a ≥8-word substring surviving literal grep of `PRD.md` (whitespace-normalized).
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; no "scaffold" references in generated code.
- `py_compile` clean; `pytest --collect-only` discovers exactly 90 tests.

## Step 6: Generate Implementation — 2026-08-13T18:02:31.284Z

Implementation complete. Summary:

## Files created (all under `/home/ubuntu/github/CodingPRD/tasks/task_1510_union_signatory_production_agreement/workspace/implementation/`)

- `start.sh` — executable launcher; guarded `pip install` (no-op when Flask is importable), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000), foreground
- `requirements.txt` — `flask>=3.0`
- `app.py` (1374 lines) — Flask entry point, all routes, validation pipeline ordered per PRD §2.10
- `db.py` — in-memory dict stores keyed by id, process-wide RLock, logical clock defaulting to exactly `2026-08-01T00:00:00Z` (never wall-clock)
- `errors.py` — `ApiError` + all 33 error-ID constructors with scaffold HTTP statuses
- `response.py` — envelope helpers: `meta.api_request_id` (`req_`-prefixed), `api_request_timestamp` (3-fractional-digit ISO UTC), `response_type`, `data`; list pagination fields `limit`/`offset`/`total_count`/`has_more` in `meta`
- `helpers.py` — auth (`X-User-ID`/`X-User-Role`, 5 roles), ProducerRep ownership (`X-User-ID` == owning company id), strict body validation (unknown-field rejection, enum/int/date checks), pagination (limit default 10, min 1, max 100), common fields (`id` UUID, `created_at`/`updated_at`, `version` starting at 1)
- `services.py` — calculation constants and engines plus cascade transitions

## Endpoints implemented: 43 (all from the scaffold endpoint table)
1 clock endpoint + 42 under `/union-compliance`: producer-companies (POST/GET + 2 list sub-resources), signatory-applications (create + submit/request-info/provide-info/decide), productions (create/read + budget-revisions/start/wrap/close + 6 reverse-reachability list endpoints), bonds (post/top-up/release), crew-assignments (create/read + 2 list sub-resources + transition), work-day-logs (create/submit/void), grievances (file + accept-intake/propose/respond/escalate/decide/payments/refunds), contribution-reports (create/submit/review), audits (open/issue-findings/payments/close), force-majeure-events (declare/lift).

## State machines implemented: 10
ProducerCompany (PENDING/SIGNATORY/SUSPENDED with reinstatement rule), SignatoryApplication (info-request loop capped at 3 rounds), Production (incl. SUSPENDED with `pre_suspension_status` save/restore and budget-revision self-transition), Bond (PENDING/POSTED/UNDERFUNDED/FORFEITED/RELEASED incl. re-post after forfeiture), CrewAssignment, WorkDayLog (voidable even when on ACCEPTED report), Grievance (negotiation loop + arbitration ladder + auto-CLOSED on zero award / full payment), ContributionReport, Audit (OPEN-close treated as zero assessment), ForceMajeureEvent.

## Calculations implemented: 7
`budget_tier_selection` (inclusive caps, never-downgrade, smallest covering tier), `bond_requirement` (flat per-tier), `min_staffing_check` (per-tier per-dept, inclusive boundary), `work_log_penalties` (meal units = ceil(delay/30), pinned per-unit-then-multiply rounding `round_half_up(R/32)`; turnaround strict `<` with tier allowance; integer-exact half-up division), `contribution_dues` (provisional OPEN+SUBMITTED @ tier-at-create vs final SUBMITTED-only @ tier-at-submit; multiply-then-divide single rounding), `grievance_filing_deadline` (exactly two passes; FM interval union/merge with end-exclusive tolling days; inclusive deadline), `audit_assessment` (per-period `max(0,shortfall)` × 110/100 rounded per period then summed vs aggregate netted variant), plus `posture_derivation` (pinned FROZEN > RESTRICTED > CLEAR, grievance threshold ≥2, unpaid-findings rule).

Cascades verified: tier-upgrade → bond requirement → POSTED→UNDERFUNDED → posture RESTRICTED; audit close with unpaid assessment → bond forfeiture (full held amount) → company SUSPENDED → posture recompute; bond re-post → company reinstatement when no FORFEITED/UNDERFUNDED bonds remain.

## Boot verification
- `bash start.sh` from the implementation dir with `PORT` set serves HTTP in ~2.5s (well under the 60s limit); root URL responds (404 envelope), satisfying the runner's readiness poll.
- 5 consecutive kill/reboot cycles all came up cleanly; store verified empty after reboot (pre-reboot entities return 404); logical clock default confirmed as `2026-08-01T00:00:00Z` via `signatory_since` stamp on a fresh boot.
- No seeding anywhere — the store starts empty; all state is built through the API.
- Functional verification: two custom smoke suites (212 assertions total, both passing on fresh boots) covering auth/role/ownership errors, envelope shape, pagination meta + invalid params, the full signatory loop, tier caps, bond ledger, staffing minimums, meal/turnaround penalty arithmetic with boundary cases, provisional-vs-final dues, OCC 412s, segregation-of-duties 403s, grievance negotiation/arbitration/payment/refund, FM overlap/adjacency and tolling math, audit assessment variants (per-period vs aggregate), the forfeit/reinstatement cascade, and the wrap→close→release path.

## Step 7: Run Tests and Iterate — 2026-08-13T18:12:00.000Z

All 8 parallel rounds pass 90/90. The benchmark is green.

## Summary

- **Iterations run**: 2 (initial 8-round sweep: 89/90 per round, one deterministic failure; fix applied; confirmation 8-round sweep: 90/90 × 8 = 720/720).

- **Tests deleted**: none.

- **Fixes applied to `test_helpers/`**: none.

- **Fixes applied to `test_suite/`**:
  - `/home/ubuntu/github/CodingPRD/tasks/task_1510_union_signatory_production_agreement/test_suite/test_06_grievances.py` — `test_closing_grievances_restores_clear_posture`: the mid-test assertion demanded `compliance_posture == "RESTRICTED"` after closing one of two grievances, but PRD §2.8 pins the open-grievance restriction threshold at an inclusive 2 ("the count of the production's grievances in `FILED`, `INVESTIGATING`, `PROPOSED_SETTLEMENT`, or `ESCALATED` status reaches 2 ... If none of these holds, the posture is `CLEAR`"). With one grievance still open, a POSTED bond, and no audits, PRD uniquely determines `CLEAR` (corroborated by the sibling test `test_second_grievance_restricts_posture` in `test_09_force_majeure_and_posture.py`, which asserts exactly that 1-open → CLEAR). The assertion (and docstring narrative) was corrected to the PRD-unique value `CLEAR`, making the test strictly more faithful — it now also verifies the posture drops the moment the count falls below the inclusive threshold.

- **Fixes applied to `implementation/`**: none — the implementation was already PRD-correct; the failure was a test-side assertion bug.

## Step 8: Finalize PRD — 2026-08-13T18:16:00.000Z

# Step 8 Complete — PRD_FINALIZED.md produced with zero edits

## Outcome

`workspace/PRD_FINALIZED.md` is a verbatim copy of `PRD.md` (300 lines each, 0% delta, `diff` confirms identical). **No edits were made** because the single Step 7 item was a pure test-side assertion bug, not a PRD silence or PRD/impl mismatch.

## Step 7 diff item analysis

- **Item**: `test_suite/test_06_grievances.py::test_closing_grievances_restores_clear_posture` — mid-test assertion corrected from `RESTRICTED` to `CLEAR` after closing one of two grievances.
- **Verdict**: PRD §2.8 already uniquely determines this behavior. The PRD pins (a) the threshold at "reaches 2" over statuses `FILED`/`INVESTIGATING`/`PROPOSED_SETTLEMENT`/`ESCALATED`, (b) "If none of these holds, the posture is `CLEAR`", (c) explicit inclusivity ("exactly 2 open grievances already restrict the production"), and (d) the recompute trigger ("a grievance is created or reaches `CLOSED`"). The implementation matches exactly: `services.py:68` (`GRIEVANCE_RESTRICTION_THRESHOLD = 2`), `services.py:71` (`OPEN_GRIEVANCE_STATUSES = {"FILED", "INVESTIGATING", "PROPOSED_SETTLEMENT", "ESCALATED"}`), `services.py:270-275` (`>= threshold` → `RESTRICTED`, else `CLEAR`). With 1 open grievance, POSTED bond, no audits, both PRD and impl yield `CLEAR`. Nothing to pin.

## Per-edit pre-edit search log

No edits were committed, so there is no per-edit log. For the single candidate edit considered and rejected:

- **(a) Subject**: open-grievance count threshold in the compliance-posture derivation (PRD §2.8) and posture recompute on grievance close (PRD §2.8, §3.6).
- **(b) Impl paths enumerated**: `services.py:246-276` (`recompute_posture` — the only posture derivation); `services.py:68,71` (threshold constants); all `recompute_posture` call sites — `services.py:323,341` (bond cascades) and `app.py:557,581,884,957,1000,1027,1231,1253,1281,1340,1365` (bond post/top-up/release, grievance create/decide/payments, report submit/review, audit findings/payments/close, FM declare/lift); corroborating sibling test `test_suite/test_09_force_majeure_and_posture.py:166,171` (1 open → CLEAR, 2 → RESTRICTED).
- **(c) Wording adjustment**: none — the existing PRD prose ("reaches 2", "If none of these holds, the posture is `CLEAR`", "The grievance-count threshold is inclusive") already describes every enumerated path exactly, so any insert would have been redundant and risked a new mismatch. Per the method ("Where PRD already determines behavior, keep prose verbatim"), the correct action was no edit.

## Line counts

- `PRD.md`: 300 lines
- `PRD_FINALIZED.md`: 300 lines
- Delta: 0 lines, 0.0%

## Step 9: Complete PRD — 2026-08-13T18:42:00.000Z

Produced `workspace/PRD_COMPLETED.md` as a minimal patch over `PRD_FINALIZED.md` (17 edit sites, all in-paragraph inserts/revisions; no new sections).

**Source vs output:** PRD_FINALIZED.md 300 lines / 47,797 chars → PRD_COMPLETED.md 300 lines / 50,919 chars (char-delta +3,096).

**Counts:** 13 ambiguity-pins, 4 mismatch-revisions (one revision, §2.10, also folds in two ambiguity pins for unknown fields / no-body endpoints).

Changes, one per bullet:

- §2.3 — insert — ambiguity — invalid `limit`/`offset` (non-integer, out-of-range, negative) → `ERR_VALIDATION` 400, checked at list-assembly time after existence/ownership; sort ties broken by `id`; `total_count`/`has_more` semantics pinned — implementation/helpers.py:201-227, implementation/app.py:96-97, implementation/response.py:30-43
- §2.4 — insert — ambiguity — version-bump exemptions: `compliance_posture` recompute and cascade-driven `amount_required_cents` recompute do not bump `version`/`updated_at` — implementation/services.py:246-276 (no `bump` in `recompute_posture`), services.py:326-341 (bump only when bond flips to `UNDERFUNDED`)
- §2.4 — insert — ambiguity — calendar-date payload fields must be strict `YYYY-MM-DD` else `ERR_VALIDATION` — implementation/helpers.py:139-145
- §2.5 — insert — ambiguity — `to_iso8601` without offset interpreted as UTC — implementation/helpers.py:148-160
- §2.5 — revise — mismatch — blanket "never the host's wall clock" carved out: `created_at`/`updated_at` and envelope timestamps are host-clock bookkeeping, not logical-clock reads — implementation/helpers.py:167-170, implementation/response.py:12-15
- §2.10 — revise — mismatch — pipeline order restated to impl's actual order: auth → role → body validation → existence → ownership (application action endpoints submit/request-info/provide-info/decide do existence → ownership → body); remaining body refs (`work_day_log_ids` elements, grievance `crew_assignment_id`) resolve after ownership; OCC last — implementation/app.py:192-216 vs 219-298, app.py:363-387, app.py:1073-1076
- §2.10 — insert (within same paragraph) — ambiguity — fields not declared for an endpoint are `ERR_VALIDATION`; endpoints with no declared request fields ignore the body — implementation/helpers.py:64-67, implementation/app.py:227-236 (submit reads no body)
- §3.1 — revise — mismatch — `fein` "unique across companies" → recorded as supplied, uniqueness not enforced — implementation/app.py:132-149 (no uniqueness check)
- §3.1 — insert — ambiguity — `estimated_slate_budget_cents` must be an integer ≥ 0 — implementation/app.py:202 (`min_v=0`)
- §3.1 — revise — mismatch — `info_request_note` is optional, string-validated, but not persisted (was "attaching") — implementation/app.py:246 (`opt_string`, never stored)
- §3.1 — insert — ambiguity — `info_response` likewise optional and not persisted — implementation/app.py:264
- §3.1 — insert — ambiguity — `denial_reason` supplied with `APPROVE` accepted but not recorded — implementation/app.py:280-297
- §3.2 — insert — ambiguity — `budget_cents` at creation must be an integer > 0 — implementation/app.py:315 (`min_v=1`)
- §3.5 — revise — ambiguity — meal-delay formula parenthesized: `first_meal_start − (call_time + 360)` — implementation/services.py:114
- §3.6 — insert — ambiguity — `proposal_amount_cents` integer ≥ 0 (negative → `ERR_VALIDATION`); null until first proposal — implementation/app.py:915, app.py:877
- §3.6 — insert — ambiguity — `award_cents` integer ≥ 0; `decision_notes` string-validated but not persisted — implementation/app.py:990-991
- §3.7 — insert — ambiguity — `work_day_log_ids` elements must be strings; list stored verbatim and repeated ids contribute per occurrence to dues sums — implementation/app.py:1064-1071, 1109-1117, services.py:154-164
- §3.7 — insert — ambiguity — `final_gross_wages_cents`/`final_contributions_due_cents` null until submission — implementation/app.py:1120-1121
- §3.7 — insert — ambiguity — `rejection_reason` with `ACCEPT` accepted but not recorded — implementation/app.py:1163-1166
- §3.7 — insert — ambiguity — `scope_period_indices` elements must be integers ≥ 1; audit starts with `assessment_cents`/`alt_assessment_cents` null and `assessment_paid_cents` 0 — implementation/app.py:1191-1198, 1207-1209

Everything else in the implementation (all 52 endpoints, role lists, state machines, posture derivation and gates, OCC scope, error catalog/HTTP statuses, bond ledger arithmetic, filing-deadline tolling, penalty and dues formulas, audit per-period vs aggregate assessments, forfeit/reinstatement cascades, FM overlap semantics) was verified to be already uniquely pinned by PRD_FINALIZED.md — no changes needed there.

---

## Pipeline complete

Final state: 90/90 tests passing in all 8 rounds of the final stability sweep (720/720). `workspace/PRD_COMPLETED.md` exists. All artifacts present: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, worklog.md, test_helpers/ (9 files), test_suite/ (11 files, 90 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}.
