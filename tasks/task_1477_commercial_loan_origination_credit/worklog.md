# Worklog — task_1477_commercial_loan_origination_credit

## Resume assessment — 2026-08-13T12:35:00.000Z

Prior run terminated mid-Step-2. Directory state on resume:

- `SCAFFOLD.yaml` (109,826 bytes) — VALID + COMPLETE. Parses as YAML; top-level keys: scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities (15), state_machines (11), concurrency_rules (2), calculations (9), validations (35), endpoints (61), errors (36), roles (8). No `scaffold_difficulty_design`/`scaffold_corner_design` keys inside (file split honored). Ends with complete roles section. Verified it contains supporting material for all nine §0.5 difficulty rules (incl. appraiser CLOSED-interval vs committee HALF-OPEN-interval overlap for rule 8, conservation invariants in exposure_ledger / participation_hold_reconciliation / participation_fee_allocation for rule 9, 4dp round_half_up inclusive boundary for rule 6, cross-entity gates for rule 7). KEPT AS-IS.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (80,504 bytes) — VALID YAML but TRUNCATED: contains only 5 of 9 required rule_ids (dual_variant_calc ×2, combinatorial_formula ×3, non_linear_state_machine ×2, transitive_cascade ×2, priority_pair_validation_conflict ×2). Missing: boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant. Existing 5 rules kept verbatim; the 4 missing rules to be appended by Step 2 completion subagent.
- `SCAFFOLD_CORNER_DESIGN.yaml` — MISSING. To be generated fresh.
- `workspace/` — EMPTY (no INSTRUCTION.md, no PRD.md). Steps 3+ not started.
- No `test_helpers/`, no `test_suite/`, no `workspace/implementation/`. Steps 5/6 not started.

Step 1 (task directory) treated as DONE per resume instructions. Pipeline resumes at Step 2 (completion pass).

## Step 3: Copy Shared Files — 2026-08-13T12:40:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1,424 bytes). Done early, while Step 2 completion subagent runs (independent artifact).

## Step 2 completion — 2026-08-13T13:20:00.000Z

Subagent finished Step 2. `SCAFFOLD_DIFFICULTY_DESIGN.yaml`: appended the 4 missing rule blocks (boundary_precision_check ×2, cross_entity_state_dependency ×2, resource_temporal_overlap ×2, compensating_invariant ×2) after the existing 5 blocks — existing 11 instances untouched; 19 instances total, all 9 rules at >=2. `SCAFFOLD_CORNER_DESIGN.yaml`: created — 118 entries (96 real instances + 22 excluded_because stubs) across all nine guide sections (entities 11, state_machines 20, calculations 13 incl. 7 stubs, validations 35, endpoints 2, errors 9 stubs, rbac 19, cross_cutting_complexity_layers 8 incl. 6 stubs, consistency_model 1). Minimal-additive SCAFFOLD.yaml fix for lint check (f): 3 officer-scoped reverse GETs added (/credit/bank-officers/{id}/policy-exceptions|document-checklist-items|funding-authorizations) + optional FK filters on GET /credit/loan-applications (originating_officer_id?) and GET /credit/financial-statements (spread_by/finalized_by_officer_id?) — 61 -> 64 endpoints. All formula-derived asserts pre-computed via Python (DSCR boundary 1.2500 vs 1.2499, fees 1,000,000/4,500,000, LARGE quorum, etc.). scaffold_lint.py: VERDICT clean (19 + 96 instances, 2,263 calls scanned). Self-audit clean: placeholder closure, union-wide name uniqueness, grounds resolvability, stub references.

### Step 2 verbatim subagent summary

Step 2 completion finished. Summary (self-contained, for worklog):

## What existed vs. what was added

**Existed (untouched):** `SCAFFOLD.yaml` (valid, complete) and `SCAFFOLD_DIFFICULTY_DESIGN.yaml` with 5 rule blocks / 11 instances. Verified append-only — the existing blocks were kept byte-verbatim (the edit anchored on the file's final two lines, which were preserved).

**Appended to `/home/ubuntu/github/CodingPRD/tasks/task_1477_commercial_loan_origination_credit/SCAFFOLD_DIFFICULTY_DESIGN.yaml`** — 4 rule blocks, 8 new instances (file now: 9 rules, 19 instances, ≥2 per rule, all names unique):
- `boundary_precision_check`: `dscr_policy_floor_inclusive_boundary` (DSCR ratio at exactly 1.2500 vs 1.2499 via finalize-spreads — cf 12,035,540 vs 12,035,058 over identical 9,628,432 annual debt service; 482-cent knife edge flips the branch) and `committee_tier_amount_inclusive_boundary` (proposed 100,000,000 → SMALL vs 100,000,001 → STANDARD via committee-decisions; decline thresholds 1 vs 2 demonstrated by actual votes). Different metrics (ratio vs amount), distinct endpoints.
- `cross_entity_state_dependency`: `application_creation_blocked_by_borrower_status` (LoanApplication→Borrower; EXITED borrower → 409) and `vote_blocked_by_session_window_state` (CommitteeDecision→CommitteeSession; vote after the clock adjourns the session → 409).
- `resource_temporal_overlap`: `appraiser_closed_interval_adjacency_conflict` (CLOSED [start,end], end==start IS a conflict at capacity 1; one-day gap admitted) and `committee_session_half_open_back_to_back_allowed` (HALF-OPEN [starts_at,ends_at), back-to-back allowed on both sides, interior overlap 409).
- `compensating_invariant`: `exposure_conserved_across_accept_and_fund_tranches` (borrower.total_exposure_cents pinned at 200,000,000 across accept + 120M + 80M releases) and `participation_hold_conserved_across_commit_release` (bank_hold + allocated == committed 80,000,000 at propose/commit/release checkpoints; fee share 500,000 returns to bank hold).

## SCAFFOLD_CORNER_DESIGN.yaml (created)

118 entries = **96 real instances + 22 excluded_because stubs** (every stub cites an existing difficulty instance name — verified). Per section: entities 11 (creation/defaults/required_fields/type_constraints/computed_fields/not_found/listing×2/system_fields/parent_relationships×2 incl. a full child-set FK reverse-reachability sweep at CLOSING), state_machines 20 (valid transitions, invalid-from rejections, terminal lockdowns, idempotency, side-effect/compensation cascades incl. withdraw-at-CLOSING and covenant waive-breach, sheet supersede/decline/expiry, session adjourn), calculations 13 (6 real: restatement input-set recompute 1.5579/1.2463, tenure+leverage tier boundaries 71.88-vs-68.75 band flip, PROVISIONAL 76.88→FULL 66.50 divergence, per-class advance rates, fee tier boundary 1,000,000 vs straddle 4,500,000, LARGE quorum chair-gate; 7 stubs), validations 35 (all remaining error ids incl. priority pairs schema→OCC→state, restatement 4-way 422s, borrower cap inclusive 402 boundary, participation headroom equality + 1-cent overflow, funding over-commitment, no-sizeable-amount, rate-lock/expiry temporal gates, stage gates), endpoints 2 (envelope shapes, computed read), errors 9 (all stubs), rbac 19 (15 denials covering every role's exclusive surface + REMAND/waive value-restrictions, 1 shared-GET grant, 3 segregation-of-duties), cross_cutting_complexity_layers 8 (2 real OCC stale-version 412s, one per concurrency rule, incl. OCC-beats-DECISION_ALREADY_OPEN; 6 stubs), consistency_model 1 (immediate visibility of accept side effects). All 36 error ids are now exercised by a real instance or a cited stub.

## SCAFFOLD.yaml edits (minimal-additive, lint-mandated)

Lint check (f) flagged 7 pre-existing unreachable audit FKs. Fixes: added 3 officer-scoped reverse GETs (`GET /credit/bank-officers/{id}/policy-exceptions`, `/document-checklist-items`, `/funding-authorizations`) and optional filters `originating_officer_id?` on `GET /credit/loan-applications` and `spread_by_officer_id?`/`finalized_by_officer_id?` on `GET /credit/financial-statements`. Endpoints 61→64; nothing removed or weakened; no design-file content needed them (pure scaffold completeness).

## Audit results

- **YAML**: all three files parse (`yaml.safe_load`); single top-level keys honored; no design keys inside SCAFFOLD.yaml.
- **scaffold_lint.py**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (19 + 96 instances, 2,263 calls scanned, 0 violations.)
- **Placeholder closure**: mechanical pass — every `${var}` in path/payload/as_user_id/assert is bound by an earlier `captures:` in the same instance; OCC `expected_*_version` values are always `${var}` or `${var} - 1` expressions, never literals.
- **Grounds resolvability**: every grounds ref resolves against §1.1–§1.7 (calculations, entity fields, state transitions, validation priorities, error ids, concurrency rule ids, endpoints, roles).
- **Call-by-call replay**: every setup/trigger chain replayed against §1.2/§1.4/§1.6 (role legality, from-states, preconditions, validation priority order, clock position, OCC version captures after each version bump). All formula-derived asserts pre-computed with Python (`pmt` factor at 700bps/60mo, DSCR 4dp round_half_up, sizing caps, fee tiers, quorum arithmetic) — verified values embedded as literals.
- **One chain restructure during audit**: `child_create_stage_gates_enforced` — the INTAKE checklist-item probe was moved into `setup_api_calls` (as a rejected probe capturing `err_doc`) because a trigger-time probe would have run at COMMITMENT where item creation legitimately succeeds.

## Step 4: Generate PRD — 2026-08-13T15:30:00.000Z

All three hard contracts pass. The PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_1477_commercial_loan_origination_credit/workspace/PRD.md`.

**SUMMARY (for worklog):**

**PRD.md line count:** 360 lines.

**Section list:** §1 Introduction (2 paragraphs, business-context angle); §2 Global Specifications with 10 subsections — 2.1 User/RBAC (headers, 8 roles, per-role identity translation: BankAdmin opaque, the other seven entity_backed to BankOfficer), 2.2 API Response Structure (byte-identical verbatim block, verified programmatically), 2.3 Pagination (limit 10/1/100, offset 0, created_at ascending, meta fields), 2.4 Resource Identity/Timestamps/Versioning (UUID no prefix, ISO 8601 3-fractional digits, version increments; names the four version-advancing operations), 2.5 Money/Ratios/Rounding (integer cents, 4dp half-up ratios, 2dp half-up scores, floored caps, per-slice fee rounding), 2.6 Logical Clock & Sweeps (startup default 2026-08-01T00:00:00Z, never wall-clock, `to_iso8601`, three sweep types with correct strict/non-strict comparisons), 2.7 OCC (both `expected_loan_application_version` checkpoints → `ERR_STALE_VERSION` 412, no race framing), 2.8 Validation Pipeline (all 35 checks as an explicit numbered priority list with error IDs and HTTP statuses), 2.9 Segregation of Duties & Officer Audit Spine (3 SoD rules + all six officer-stamp fields), 2.10 Flat Collections & Path Validation (FK linkage narrative, left-to-right 404); §3 Business Logic with 8 subsections (3.1 officers/borrowers/front door + exposure ledger, 3.2 intake/spreading/dual-variant DSCR + provisional rating, 3.3 exception-review loop, 3.4 appraiser capacity + dual-basis collateral, 3.5 pinned-order sizing + committee hierarchy/quorum/remand, 3.6 term sheets/commitment letters/tiered fee/expiry cascade, 3.7 documentation/closing/funding pipeline, 3.8 covenant breach cascades + participations + withdrawal compensation set); §4 Endpoint Definitions (64 rows, 4 columns: Method/Path/Description/Authorized Roles); §5 Error Code Catalogue (36 rows, 2 columns).

**Coverage self-audit (all PASS):** Contract 1 Field-Name Coverage — 97/97 required identifiers (all 15 entities' fields + endpoint request/query/path identifiers incl. `to_iso8601`, `expected_loan_application_version`, `outcome`, `to`, `vote`, `measured_value`, vote-record sub-fields `officer_id`/`vote`/`cast_at`) present in backticks, 0 missing (verified by script). Contract 2 Rule Coverage — walked manually: 35/35 validations with priority expressed in the numbered §2.8 pipeline plus per-endpoint orderings restated at busy gates (finalize-spreads: state→SoD→statements; submit-to-committee: state→accepted→settled→sizeable; release: state→HIGH exceptions→closing conditions→rate lock→letter state→cumulative cap; votes: recusal/duplicate/remand-role/window); 2/2 OCC rules with endpoint + field + `ERR_STALE_VERSION`/412; all 53 state-machine transitions across 11 machines expressed with from/to states, preconditions paired to error IDs, and side effects (incl. the 9 withdrawal sibling transitions via a unified compensation-set paragraph with stage-specific addenda); 9/9 calculations fully reconstructed in prose (dual DSCR with 7.00%/12 monthly rate and 25% addback cap and 15% revenue haircut, four-factor rating with all tiers/weights/0.80 renormalization/10 bands, 4-step pinned sizing with both `ERR_NO_SIZEABLE_AMOUNT` reject points, dual-basis collateral with advance-rate table and 0.85 haircut, tiered fee with pinned per-slice rounding order, quorum tiers with inclusive $1M/$10M bounds and Reg-O/HIGH-exception bump, hold reconciliation and per-share fee allocation in `created_at` ASC order with the bank remainder absorbing rounding, exposure-ledger conservation); all endpoint `applies_to` scopes enumerated; field defaults/nullability (`is_reg_o_insider` false, `max_concurrent_engagements` 2, `is_required` true, `severity` STANDARD, counters 0, DSCR null until finalize, `fee_share_cents` null until COMMITTED and cleared on RELEASED, `bank_hold_fee_cents` null until letter) all stated. One ambiguity found and fixed during the audit: the DSCR factor and collateral-coverage factor initially shared the label "coverage" in the rating formulas — renamed to "debt-service-coverage factor" vs "collateral-coverage factor" so both PROVISIONAL and FULL formulas reconstruct unambiguously. Contract 3 §3 Path Purity — 727 backtick tokens scanned, 0 path/method/combo violations (verified by script).

**Zero-Silence confirmations:** every scaffold-declared behavior appears as a full sentence — all 36 error IDs mentioned in §1–§3 (verified by script); all 83 enum/state values (8 roles, 13 application states, 8 rule codes, 5 collateral classes, 4 covenant types, etc.) appear as exact strings; all 64 endpoints in the §4 table; all side-effect cascades (decline, 3-hop expiry, withdrawal compensation, first-release quartet, 2-hop breach, cure/waive restoration, restatement supersede, term-sheet supersede) stated with their full hop lists; the closed-vs-half-open interval distinction for appraiser windows vs committee sessions (adjacent end==start conflicts for appraisers, back-to-back allowed for sessions) is stated explicitly.

**Deliberate scattering/layout decisions:** §2.8 was made an explicit numbered 35-stage pipeline (contract zone) so validation priority is unambiguous, while §3 scatters the trigger conditions into workflow prose near each gate; rating factors split across §3.2 (provisional: DSCR/leverage/tenure tiers + renormalization) and §3.5 (full: collateral-coverage tier + 4-factor weights); the $50M single-borrower cap introduced in §3.1 at creation and reused as sizing headroom in §3.5; the exposure ledger formula placed in §3.1 with the compensating-pair behavior reinforced in §3.7 funding; OCC mechanism specified in §2.7 and re-narrated at the two checkpoints in §3.5/§3.6; fee constants embedded as dollar figures ("first $1,000,000.00 at 1.00%…") rather than cent constants; endpoints referenced in §3 only via state-pair framing (`INTAKE` → `SPREADING`) and role+verb phrasing ("a `CreditPolicyOfficer` clears the review"); §4 table kept minimal (no request/response bodies) and §5 has no conditions column.

## Step 5: Generate Unit Tests — 2026-08-13T16:50:00.000Z

Task complete. Summary for worklog.md:

## task_1477_commercial_loan_origination_credit — unit test generation

**Tests emitted: 134 total — Queue A (Difficulty): 38 tests (19 instances × 2, at the required ≥2 per instance); Queue B (Corner): 96 tests (96 non-stub instances × 1). Zero instances skipped.** The 22 `excluded_because:` stubs (7 calculations, 9 errors, 6 cross_cutting_complexity_layers) were not translated; all 22 `difficulty_instance` cross-references verified to resolve to real §1.8 instance names.

**Coverage verification (scripted audit, all clean):**
- Every non-stub §1.8/§1.9 instance maps to exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` docstring tag; every test carries exactly one tag; no tag points to a non-existent instance; no `pytest.mark.skip/skipif/xfail` anywhere.
- Every test docstring's PRD citation verified by a sliding 12-word window grep against `workspace/PRD.md` (0 failures).
- All test-module `from test_helpers import ...` names statically resolve against the generated helpers; all files compile.

**Instances skipped:** none. Two assertion-level adjustments were made under the PRD-first two-condition filter (instances themselves still fully translated):
1. `Difficulty/combinatorial_formula/sizing_circular_dependency_pinned_order` — the design's pre-computed `risk_rating == 4` contradicts the PRD formula (FULL score 0.4·20+0.3·100+0.2·25+0.1·100 = 53.00 → band "at least 50 yields 5"); the test asserts the PRD-derived `risk_rating == 5` with the §3.5 citation. All other asserted values (26,934,396 sizing, 0.6734 unrecomputed DSCR, OPEN HIGH LTV/coverage exceptions) verified numerically against PRD formulas before emission.
2. Absolute `version == 1` claims (PRD §2.4 states only "starts at its initial value", so absolute values are not uniquely derivable) were emitted as relative +1-increment assertions, which PRD §2.4 does pin. Unstated null defaults (`proposed_amount_cents`, `rating_basis`, appraisal `eligible_value_cents` pre-acceptance) were dropped or weakened to `.get() is None` where PRD does not name the pre-computation value.

**test_helpers/ files:** `__init__.py` (barrel), `types.py` (15 TypedDicts + 20 status/role enums), `api_client.py` (ApiClient subclassing GenericApiClient, one method per PRD endpoint incl. `set_clock`), `api_errors.py` (ApiErrorId + 36-entry HTTP map registered via `set_error_http_status_map`), `assertions.py` (per-entity structural asserts + `assert_exposure_conservation`), `factories.py` (per-entity payload factories + 12 pinned STATEMENT_SHAPES: BEACON, MERIDIAN, WINDOW, HARBOR, COLD, THIN, TIER, TIER3, LARGE, TENURE, NOSIZE, BOUNDARY_PASS/FAIL, BEACON_RESTATED), `constants.py` (rates, caps, tiers, quorum tables, rationales), `test_users.py` (opaque BankAdmin constant + per-instance builders for the 7 entity-backed roles), `fixtures.py` (officer bench `setup_officers`, ~30 single-step helpers, and the staged composite chain `deal_intake → deal_spreading → deal_underwritten → deal_appraisal_review → deal_committee_review → deal_decision_open → deal_approved → deal_commitment → deal_letter_issued → deal_documentation → deal_closing → deal_funded`, all identity-threaded with real BankOfficer ids).

**test_suite/ files:** `conftest.py` + 17 test files: `test_01_creation_and_reads`, `test_02_borrower_status_and_limits`, `test_03_envelope_versioning_and_consistency`, `test_04_statements_and_spreading`, `test_05_dscr_calculations`, `test_06_risk_rating`, `test_07_appraisals`, `test_08_sizing_and_committee_setup`, `test_09_committee_sessions_votes`, `test_10_term_sheets_and_letters`, `test_11_documentation_and_exceptions`, `test_12_funding`, `test_13_covenants`, `test_14_participations`, `test_15_withdrawal_and_expiry`, `test_16_rbac_and_pipeline`, `test_17_fk_reachability`.

## Step 6: Generate Implementation — 2026-08-13T17:05:00.000Z

All verification complete. Final summary:

## Implementation complete — task_1477_commercial_loan_origination_credit

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1477_commercial_loan_origination_credit/workspace/implementation/`):

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | Launcher (details below) |
| `requirements.txt` | 1 | flask |
| `app.py` | 56 | Flask entry, before-request auth, blueprint registration, JSON error handlers (ApiError/404/405/500), `0.0.0.0:$PORT` |
| `db.py` | 69 | In-memory store (15 entity dicts), logical clock pinned at `2026-08-01T00:00:00Z`, UUID ids, 3-fractional-digit ISO timestamps, `version` counter, monotonic `_seq` tiebreaker |
| `errors.py` | 58 | `ApiError` + full 35-entry error-id catalog with exact HTTP statuses |
| `response.py` | 47 | Envelope: `meta{api_request_id, api_request_timestamp}`, `response_type`, `data`; list meta adds `limit/offset/total_count/has_more` |
| `middleware.py` | 41 | `X-User-ID`/`X-User-Role` presence + 8-role recognition; per-endpoint role gating |
| `validation.py` | 154 | Body/pagination schema validators (strict int/bool/enum/date/datetime, NAICS 6-digit, ranges) |
| `serialize.py` | 234 | Per-entity serializers; derived fields computed live |
| `routes/` | 1,608 | 14 modules: officers, borrowers, applications, statements, exceptions, appraisals, committee, termsheets, letters, checklist, funding, covenants, participations, clock (+`common.py` helpers) |
| `services/` | 395 | `money.py` (Decimal half-up/floor primitives), `underwriting.py` (dual-variant DSCR, 4-factor risk rating with PROVISIONAL renormalization, pinned-order sizing), `collateral.py` (dual-basis advance rates), `fees.py` (tiered origination fee, per-share fee allocation), `exposure.py` (exposure ledger, hold reconciliation, collateral aggregates), `policy.py` (exception severity map, condition-keyed auto-exception create/refresh, never-resurrect-WAIVED) |

**Subsystem organization**: state machines are enforced per-endpoint in route modules with the PRD §2.8 pipeline order (auth → role → path 404 → schema → OCC → state → amend-window → commitment → SoD → business), each mutating entity `touch()`ed (version+1, updated_at). All calculations use `Decimal` (no floats for money); borrower exposure, bank hold amount/fee, collateral aggregates, and funded totals are **derived at read time** from live letter/funding/participation/appraisal state, so the conservation invariants hold by construction. Cascades (decline, withdraw, expiry sweep, covenant breach/cure/waive) are explicit loops bumping each child's own version/timestamp. OCC on `expected_loan_application_version` guards term-sheet creation and decision opening (412). Clock sweeps on `_clock/set_current_utc` expire ISSUED letters (`expiry_date <=` clock date, with 3-hop cascade), expire ISSUED term sheets (`expires_at <` now), and adjourn sessions (`ends_at <=` now), atomically.

**start.sh contract confirmed**: guards `pip install` behind `python3 -c "import flask"`, `exec python3 app.py` in foreground, binds `0.0.0.0:$PORT` (default 10000); verified booting from a foreign cwd on a custom port and under the harness's per-test-server restarts. **Storage is in-memory only, zero seed data** — the store is empty at every boot; all state is built via the API.

**Test results**: official suite `prd-bench-local-run --isolation per-test-server`: **103/134 pass**. I classified every one of the 31 failures by running each solo: all are test-side defects no implementation can fix — (a) fixture `KeyError: 'apm'/'adm'` where `deal_appraisal_review`/`deal_approved` build officer benches lacking a role the test then uses (fails before any HTTP), (b) `NameError` from missing imports in test files (`deal_letter_issued`, `deal_committee_review`), (c) a fixture assumption that the default BEACON/30M-cent deal sizes to `proposed == 200_000_000` (STANDARD), which contradicts the PRD sizing formula `min(requested, dscr_max, ltv_max, headroom)` and the suite's own passing sizing tests (`test_dscr_cap_binds_sizing`, both tier-boundary tests). One genuine implementation bug was found and fixed during this loop (amount-vs-proposed ERR_VALIDATION now precedes the OCC check on POST /credit/term-sheets, 102→103). Three custom end-to-end smoke suites (full pipeline, exception/remand/Reg-O/LARGE-quorum/decline/withdraw cascades, restatement/rate-lock/expiry/pagination edge cases) all pass on fresh boots with hand-verified arithmetic.

**PRD interpretation decisions** (ambiguous points): body-FK references to nonexistent resources → `ERR_VALIDATION` (PRD scopes 404 to path ids only); statement money fields accept any integer (zero/negative EBITDA must be allowed) while transactional amounts are strictly >0; `version` starts at 1 and increments on every mutation including cascades; the EXCEPTION_REVIEW re-run recomputes only DSCR + the four finalize-spreads exceptions (risk rating is recomputed at finalize-spreads/submit-to-committee only, per the calculation's trigger list); votes on a withdrawn application's still-OPEN decision are rejected with `ERR_INVALID_STATE` (PRD's "rejected by session/state checks"); `bank_hold_amount_cents` uses the application's letter once it exists (including DRAFT); covenant `last_reviewed_period` updates on every review; funding-release gate order follows the PRD §3.7 narrative (state → HIGH exceptions → checklist → rate lock → letter state → cap) where it conflicts with scaffold priority numbering, per PRD precedence.

## Resume assessment — 2026-08-13T17:20:00.000Z

Second resume. Directory state verified:
- `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml` — complete (Step 2 done).
- `workspace/INSTRUCTION.md` (53 lines), `workspace/PRD.md` (360 lines) — complete (Steps 3–4 done).
- `test_helpers/` (9 modules) + `test_suite/` (conftest + 17 test files, 134 tests) — complete (Step 5 done).
- `workspace/implementation/` (app + 14 route modules + 6 services + start.sh) — complete (Step 6 done).
- Stale `results.{1..8}.json` from Step 6's own verification run: all 8 rounds 103/134 with the same 31 failures. Step 6 classified them as test-side defects and fixed 1 implementation bug itself, but **Step 7 (the fix-loop subagent) never ran** — no Step 7 entry in this worklog.

Pipeline resumes at Step 7. Step 7 owns re-diagnosis from scratch (its STEP 0 re-reads results fresh); Step 6's failure classifications are advisory only.

## Step 7: Fix loop — 2026-08-13

Re-diagnosed from scratch (STEP 0): fresh 8-round sweep reproduced exactly the 31 stale failures (103/134 x8, zero flakiness). All 31 traced to test-side artifacts; one latent PRD-fidelity bend from Step 6 was also found and corrected. Final validation: **134/134 in all 8 parallel rounds, union of failures empty.**

Fixes applied:

- `test_helpers/fixtures.py` `deal_appraisal_review`: default officer bench now includes `apm` (tests using this fixture order/manage appraisals; bench previously ended at underwriting roles rm/an/po). Fixed 13 KeyError 'apm' failures (test_06 x1 via call-site, test_07 x11, test_08 x1).
- `test_helpers/fixtures.py` `deal_committee_review`: default deal is now the MERIDIAN shape at a 200,000,000-cent request (was inheriting the factory default BEACON/30,000,000, which sizes to SMALL and contradicts the STANDARD-session default of `deal_decision_open` and three tests' verbatim assertions of proposed==200,000,000 / requested==200,000,000; MERIDIAN's DSCR cap ~336.7M and LTV cap 320M both clear the request, so proposed==200,000,000 per PRD 3.5). Bench default also gained `ch` (committee-stage work needs the chair). Fixed the 11-test ERR_SESSION_LEVEL_MISMATCH cluster + test_08 test_session_level_mismatch_rejected + test_11 amend assertion.
- `test_suite/test_03`: added missing `deal_letter_issued` import (NameError).
- `test_suite/test_10`: added missing `deal_committee_review` import (NameError); `_approved_200m` now forwards **kw; supersede test passes officer_keys incl. `adm` (it reads letters via adm headers).
- `test_suite/test_11`: added missing `deal_committee_review` import (NameError).
- `test_suite/test_06`: `deal_underwritten(officer_keys=(rm,an,po,apm))` — the test orders appraisals after underwriting.
- `test_suite/test_09`: `test_decision_create_denied_for_committee_member` passes officer_keys incl. `ch`+`m1` (creates a session, attempts a member-role decision create).
- `test_suite/test_14`: `test_no_participation_persisted_on_rejection` passes officer_keys incl. `adm` (issues a letter in its control branch).
- `workspace/implementation/routes/termsheets.py` `create_term_sheet`: reverted Step 6's pipeline bend — the amount==proposed ERR_VALIDATION check is entity-dependent (business rule), so it now runs AFTER the OCC check and the state gate, per PRD 2.8 stage 5 verbatim ("runs after schema validation but before every remaining state and business check") and the PRD 3.6 narrative order (state, then amount equality).
- `test_suite/test_10` `test_schema_validation_precedes_occ_check`: probe changed from amount 199,999,999 (schema-valid, business-invalid — it pinned the anti-PRD ordering) to amount_cents 0, a true stage-4 violation per PRD 2.8 verbatim ("monetary amounts strictly greater than zero"); assertion (ERR_VALIDATION, not ERR_STALE_VERSION) unchanged.

No tests deleted. No skips/xfails added. No PRD-required implementation check was weakened.

## Step 7: Run Tests and Iterate — 2026-08-13T17:50:00.000Z

All done. Final state: 134/134 passing in all 8 parallel rounds with an empty failure union, after the last fix batch.

## Summary

**Iterations run:** 3 eight-round sweeps — (1) fresh re-diagnosis reproducing the 31 stale failures (103/134 × 8, zero flakiness), (2) validation of the fixture/import fixes (134/134 × 8), (3) validation after the OCC-ordering correction (134/134 × 8, clean).

**Tests deleted:** none. Every failing test traced to verbatim PRD prose; all failures occurred in fixture setup, not assertions.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1477_commercial_loan_origination_credit/test_helpers/fixtures.py` `deal_appraisal_review` — default officer bench now includes `apm` (AppraisalManager); tests using this fixture order/manage appraisals, but the bench previously ended at underwriting roles. Fixed 12 KeyError 'apm' failures.
- Same file, `deal_committee_review` — default deal is now the MERIDIAN statement shape at a 200,000,000-cent request with `ch` added to the bench. Previously it inherited the factory default BEACON/30,000,000, which sizes to SMALL (PRD §3.5: proposed = min(requested, DSCR cap, LTV cap, headroom)), contradicting `deal_decision_open`'s STANDARD default session and three tests' verbatim-pinned assertions of proposed == 200,000,000. With MERIDIAN, DSCR cap (~336.7M) and LTV cap (320M) both clear the request, so proposed == 200,000,000 uniquely per the PRD formula. Fixed the 11-test ERR_SESSION_LEVEL_MISMATCH cluster plus the sizing assertion.

**Fixes applied to `test_suite/`:**
- `test_03_envelope_versioning_and_consistency.py` — added missing `deal_letter_issued` import (NameError).
- `test_10_term_sheets_and_letters.py` — added missing `deal_committee_review` import; `_approved_200m` now forwards `**kw`; the supersede test passes a bench including `adm` (it reads commitment letters).
- `test_11_documentation_and_exceptions.py` — added missing `deal_committee_review` import.
- `test_06_risk_rating.py` — `deal_underwritten(officer_keys=(rm,an,po,apm))`; the test orders appraisals post-underwriting.
- `test_09_committee_sessions_votes.py` — `test_decision_create_denied_for_committee_member` bench gains `ch`+`m1`.
- `test_14_participations.py` — `test_no_participation_persisted_on_rejection` bench gains `adm` (control branch issues a letter).
- `test_10` `test_schema_validation_precedes_occ_check` — probe changed from amount 199,999,999 (schema-valid but business-invalid, which pinned an anti-PRD ordering) to `amount_cents: 0`, a genuine stage-4 violation per PRD §2.8 verbatim ("monetary amounts strictly greater than zero"); assertion unchanged.

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1477_commercial_loan_origination_credit/workspace/implementation/routes/termsheets.py` `create_term_sheet` — reverted Step 6's pipeline bend: the amount==proposed ERR_VALIDATION check is entity-dependent (a business rule, not stage-4 body schema), so it now runs after the OCC check and the TERM_SHEET_NEGOTIATION state gate, per PRD §2.8 stage 5 ("runs after schema validation but before every remaining state and business check") and the §3.6 narrative order.

No skips/xfails, no weakened assertions, no PRD-required check removed, no tests deleted.

## Step 8: Finalize PRD — 2026-08-13T17:55:00.000Z

Done. `PRD_FINALIZED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_1477_commercial_loan_origination_credit/workspace/PRD_FINALIZED.md`.

## Summary

**Line counts:** PRD.md 360 lines, PRD_FINALIZED.md 360 lines (0% line-count delta; one inline insertion of one sentence into an existing paragraph, §3.6 line 210).

**Changes (one edit total):**
- §3.6 (Term Sheets, first paragraph) — insert — pinned that the `amount_cents == proposed_amount_cents` ERR_VALIDATION check is entity-dependent and therefore NOT a stage-4 body-schema check: it is evaluated after the OCC check (stage 5) and after the `TERM_SHEET_NEGOTIATION` state gate (stage 6), so a doubly-failing request yields ERR_STALE_VERSION or ERR_INVALID_STATE respectively, regardless of the amount — `implementation/routes/termsheets.py:37-51`.

**All other step_7_diff items required no PRD edit:** the fixture fixes (`deal_appraisal_review` bench adding `apm`; `deal_committee_review` switching to the MERIDIAN statement shape at a 200,000,000-cent request so DSCR/LTV caps clear the request and `proposed == 200,000,000` uniquely per the §3.5 min-formula; added `ch`/`m1`/`adm` bench roles) and the test-file import/forwarding fixes were pure test-side bugs — the PRD already pins the AppraisalManager orders appraisals (§3.4, §4 table), the sizing formula (§3.5), and who issues letters/opens decisions (§3.5/§3.6/§4). The `test_schema_validation_precedes_occ_check` probe change to `amount_cents: 0` is verbatim-pinned by §2.8 stage 4 ("monetary amounts strictly greater than zero").

**Pre-edit search log (the single edit):**
- (a) Subject: pipeline placement of the entity-dependent amount==proposed ERR_VALIDATION check at term-sheet issuance.
- (b) Paths enumerated and read: `routes/termsheets.py` `create_term_sheet` (full function, lines 17-72: roles → `req_*` schema incl. `amount<=0` ERR_VALIDATION → `body_fk_exists` → OCC → state gate → equality check → supersede → create); `routes/termsheets.py` `respond_term_sheet` (no amount check, unaffected); grep for `proposed_amount_cents` across `implementation/` (hits in `serialize.py:53`, `routes/committee.py:33` level computation, `services/underwriting.py:176` sizing, `routes/applications.py:106,249` — none perform an amount-equality validation, so the edit's subject is unique to term-sheet issuance); grep for `ERR_STALE_VERSION`/`expected_loan_application_version` in `routes/` (only `termsheets.py` and `committee.py`); read `committee.py` `open_decision` (lines 94-144) confirming the same OCC → state → business ordering so §2.8 stage 5's "before every remaining state and business check" phrasing needed no change.
- (c) Wording adjustment: the inserted sentence is scoped explicitly to "this endpoint" (term-sheet issuance) and explicitly limits stage-4's scope to "the request body's own ranges" rather than making a universal claim about all ERR_VALIDATION checks, so it cannot mis-describe the committee endpoint or any other route's validation ordering.

## Step 9: Complete PRD — 2026-08-13T18:25:00.000Z

The diff is complete and verified. All edits are in place. Final summary:

## PRD_COMPLETED.md produced

**Source**: `workspace/PRD_FINALIZED.md` (copied, then edited in place as `workspace/PRD_COMPLETED.md` per method — PRD.md untouched).

**Size**: 360 → 360 lines; 72,445 → 78,040 chars (**+5,595 chars**). All edits are in-paragraph inserts/revisions; no new sections.

**Counts**: 19 ambiguity-pins, 1 mismatch-revision (20 edited passages total).

### Changes

- **§2.3** — insert — ambiguity — pins invalid `limit`/`offset` → `ERR_VALIDATION`, `has_more` = (`offset` + returned-count < `total_count`), creation-timestamp ties broken by insertion sequence — `validation.py:126-154`, `response.py:29`, `routes/common.py:21-26`
- **§2.4** — insert — ambiguity — request-supplied date/datetime fields (session `starts_at`/`ends_at`, sheet `expires_at`, letter `expiry_date`/`rate_lock_expires_at`, engagement dates) stored and echoed verbatim as supplied; comparisons parse them as instants — `routes/committee.py:69-70`, `routes/termsheets.py:65`, `routes/letters.py:49-52`
- **§2.4** — revise — ambiguity — `version` "starts at its initial value" → "starts at 1" — `db.py:56-64`
- **§2.5** — insert — ambiguity — ratios serialize as JSON numbers; 4th-decimal trailing zero not textually preserved (1.4730 → 1.473) — `services/money.py:25-29`
- **§2.6** — insert — ambiguity — clock-set applies any supplied instant unconditionally; no monotonicity check; sweep runs against the new instant — `routes/clock.py:16-17`
- **§2.8 stage 4** — revise — ambiguity — scopes "monetary amounts strictly greater than zero" to the five transactional amounts (request/sheet/appraisal-values/funding/allocated); statement figures admitted as any-sign integers; offset-less datetimes read as UTC; body-FK existence folded into stage 4; unrecognized body fields ignored — `routes/statements.py:20-24,33`, `validation.py:105-117`, `routes/common.py:14-18`
- **§2.10** — insert — ambiguity — body-carried FK to a nonexistent resource → `ERR_VALIDATION` (not 404); `restatement_of_id` remains the `ERR_RESTATEMENT_TARGET_INVALID` exception — `routes/common.py:14-18`, `routes/statements.py:35-36`
- **§3.1** — insert — ambiguity — borrower PATCH gates only the target value, so a `SUSPENDED` borrower may be set directly back to `ACTIVE`/`EXITED` — `routes/borrowers.py:86-101`
- **§3.1** — revise — ambiguity — new application also carries nulls in `rating_basis`, `proposed_amount_cents`, `committee_level_required` until stamped — `routes/applications.py:102-107`
- **§3.2** — insert — ambiguity — the eight raw statement figures are validated only as integers; §2.8's strictly-positive rule does not apply to spreads — `routes/statements.py:33` (`req_int` only)
- **§3.2** — insert — ambiguity — `total_assets_cents` ≤ 0 → leverage ratio undefined → leverage factor contributes 20 points — `services/underwriting.py:104-105`
- **§3.3** — insert — ambiguity — exception waiver gated only on the exception being `OPEN`, never on the application's stage (test_12 relies on waiving `LTV_MAXIMUM`/`COLLATERAL_COVERAGE_MIN` while in `CLOSING`); re-run in `EXCEPTION_REVIEW` recomputes only the two DSCRs plus the four finalize-time exceptions, leaving `risk_rating`/`rating_basis` unchanged — `routes/exceptions.py:39-40`, `routes/applications.py:54-64`
- **§3.5** — insert — ambiguity — sizing step two's intermediate monthly payment (max annual ÷ 12) is not rounded; only the final principal cap is floored — `services/underwriting.py:185-186`
- **§3.5** — insert — ambiguity — LTV/liquidation exception tests and the collateral-coverage tier compare exact unrounded quotients; the collateral re-test applies §3.3 refresh semantics (resolve-by-change, no resurrection of `WAIVED`) — `routes/applications.py:255-269`, `services/underwriting.py:118-128`, `services/policy.py:52-68`
- **§3.5** — revise — ambiguity — vote gate enumeration now requires the application to still be in `COMMITTEE_REVIEW` (`ERR_INVALID_STATE`); the withdrawn-decision sentence now names `ERR_INVALID_STATE` at the state check — `routes/committee.py:162-166`
- **§3.6** — revise — **mismatch** — rate-lock bound "no later than 23:59:59 UTC" → "no later than the end of the day on the expiry date — 23:59:59.999 UTC inclusive" (impl admits sub-second times up to .999) — `routes/letters.py:43-46`
- **§3.7** — insert — ambiguity — checklist transition endpoint check order: schema (incl. rationale length) → from-state legality → policy-officer-only → `CRITICAL` severity; waiver on a non-`PENDING`/`RECEIVED` item fails `ERR_INVALID_STATE` before role is consulted — `routes/checklist.py:83-100`
- **§3.7** — revise — ambiguity — `threshold_value` (and review `measured_value`) validated only as a JSON number; stored, echoed, and compared exactly as supplied; the 4dp/integer-cent phrasings are domain meaning, not input restrictions — `routes/covenants.py:59,69-74`
- **§3.7** — insert — ambiguity — every funding release advances the application's `version` (its `funded_amount_cents` changes), including subsequent tranches that leave it `FUNDED` — `routes/funding.py:106-122`
- **§3.8** — revise — ambiguity — covenant review semantics: `last_reviewed_period` recorded on every review pass or fail; a pass from `CURED` returns to `COMPLIANT`; a fail while `BREACH_PENDING` re-fires the cascade stacking a fresh `COVENANT_BREACH` each time; cure/waiver resolves every linked `OPEN` exception; a `WAIVED` covenant is terminal for reviews (`ERR_INVALID_STATE`) — `routes/covenants.py:99-123`, `services/policy.py:71-84`
- **§3.8** — revise — ambiguity — withdrawal terminal set enumerated as `FUNDED`, `DECLINED`, `WITHDRAWN`, `EXPIRED` — `routes/applications.py:32,303-304`

**Verified already-pinned (no change)**: the known Step 8 pins all check out against the impl — funding-release gate order, term-sheet amount-equality placed after OCC + state gate, `bank_hold_amount_cents` live from letter creation, DSCR refresh scope in `EXCEPTION_REVIEW`, closed-interval appraiser windows vs half-open session windows, tier/quorum tables, fee tiering with per-slice half-up then bank-remainder absorption, exposure conservation, and the OCC pair being the only version-carrying endpoints.
