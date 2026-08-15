# Worklog — task_1614_airport_noise_complaint_abatement_program

## Step 1: Create Task Directory — 2026-08-14T01:42:00.000Z

Task directory `tasks/task_1614_airport_noise_complaint_abatement_program/` and `workspace/` pre-created by the pipeline dispatcher (Step 1 treated as DONE per invocation args). Verified directory exists and is empty.

## Step 2: Generate Scaffold — 2026-08-14T03:00:00.000Z

Done. All three scaffold artifacts are generated, cross-audited, and lint-clean.

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_1614_airport_noise_complaint_abatement_program/SCAFFOLD.yaml` — §1.0–§1.7 only (verified: neither `scaffold_difficulty_design` nor `scaffold_corner_design` appears)
- `/home/ubuntu/github/CodingPRD/tasks/task_1614_airport_noise_complaint_abatement_program/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1614_airport_noise_complaint_abatement_program/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

## Counts

| Metric | Count |
|---|---|
| Entities | 15 |
| State machines | 13 (incl. parallel-dimension pair on SoundInsulationApplication) |
| Calculations | 11 |
| Validation rules | 13 (priority-ordered, 13 priority tiers) |
| Endpoints | 99 |
| Errors | 61 |
| Roles | 7 |
| OCC concurrency rules | 3 |
| §1.8 instances | 26 (3 per rule; 2 for resource_temporal_overlap) |
| §1.9 instances | 61 (58 active + 3 `excluded_because` stubs); 822 total calls lint-scanned |

## Lint verdict (verbatim)

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

(Fixed en route: two `FK_REVERSE_UNREACHABLE` findings — sub-resource list paths renamed to the literal `{id}` parent placeholder the linter's prefix check expects.)

## Notable design decisions (difficulty levers pushed)

- **Profile**: compliance/audit primary + temporal-windowing secondary; flat topology with FK links + a self-referential `NoiseStudy.supersedes_study_id`; segregation-of-duties role model (report approver ≠ creator, enforced via `created_by_user_id`).
- **Dual-variant calcs on 3 domains**: correlation STRICT/RELAXED windows (complaints), parcel DNL PRELIMINARY (modeled−1.5) vs FINAL (measured) keyed on study adoption (parcels), grant PROVISIONAL vs FINAL with delta reconciliation (applications/fund).
- **Combinatorial modes (a)/(b)/(c) all present**: tiered engine-class × grace × standing-multiplier curfew score; pinned per-component rounding in grant split (1,111,115¢ → 1,277,783 vs naive 1,277,782); circular-looking annoyance index where tier is keyed on base only (base 38.5 → MODERATE, final 44.5 must NOT re-tier to HIGH).
- **Cascades**: study-adoption depth-3 chain (parcel flip → application auto-INELIGIBLE/rescore → fund pipeline), event-classification chain with compensation on reclassify (58.0 → 73.0 corroboration flip + auto-notification at count ≥3), escalation demotion → grace revocation (PROBATION ×1.25 violation multiplier), withdraw → DRAFT auto-close.
- **OCC (3 true CREATE-supersede/stale-update races)**: report PATCH, complaint correlate (re-correlation from CORRELATED is legal, so only OCC rejects staleness), issue-offer on fund version. All use `${var}`-captured versions; deliberate-stale tests replayed sequentially.
- **Boundary battery**: ≥10/≥25 standing thresholds, DNL 65.0 eligibility, uptime 80.0% (8,640 vs 8,700 outage minutes in a 43,200-minute window), confidence exactly 60.0, waterfall 50% partial floor, closed-vs-half-open interval overlap semantics (curfew minute 1300 conflicts; outage adjacency allowed).
- **Deterministic time**: `POST /_clock/set_current_utc` with fixed startup default 2026-08-01T00:00:00Z; notification overdue sweep on clock advance; offer expiry swept on read so `ERR_OFFER_EXPIRED` stays reachable on the write path.
- All formula-derived asserts were pre-executed in Python (correlation 84.0/71.2/60.0/50.0, grant splits 8,805,555/1,277,783/4,600,000/3,680,000, DNL 53.6, annoyance 38.5/44.5, compliance 800.0/625.0, waterfall full/partial/skip with 10,000,000 reserved) — no unresolved expressions left for downstream generators.

## Step 3: Copy Shared Files — 2026-08-14T03:02:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1614_airport_noise_complaint_abatement_program/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T03:35:00.000Z

PRD generation complete. All three hard contracts PASS.

## Summary

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_1614_airport_noise_complaint_abatement_program/workspace/PRD.md`
**Line count:** 427 lines (dense multi-sentence paragraphs)

**Section list:**
- §1 Introduction (2 paragraphs — business context + design pressures)
- §2 Global Specifications: 2.1 RBAC (7 roles, identity translations for opaque vs entity-backed `OperatorRep`/`Complainant`) · 2.2 API Response Structure (byte-identical verbatim block, verified programmatically) · 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending) · 2.4 Logical Clock and Lazy Sweeps (startup `2026-08-01T00:00:00Z`, `to_iso8601`/`current_utc`, escalation sweep on clock advance, offer expiry lazy on read) · 2.5 Common Resource Properties (incl. MonitorOutage exception: no `updated_at`/`version`) · 2.6 OCC (3 rules with exact error IDs and HTTP 412) · 2.7 Units/Precision/Rounding · 2.8 Community Zones · 2.9 Cascades A–D · 2.10 Nested Retrieval (left-to-right 404) · 2.11 Validation Order (13 gates, explicit priority prose)
- §3 Business Logic: 3.1 Registry & standing machine · 3.2 Flights & curfew compliance scoring · 3.3 Monitors/outages/events & DNL · 3.4 Complaint lifecycle & correlation · 3.5 Notifications & escalation · 3.6 Outreach & annoyance index · 3.7 Studies & parcels · 3.8 Insulation grants · 3.9 Quarterly reports
- §4 Endpoint table (99 rows, 4 columns) · §5 Error catalogue (61 rows, 2 columns)

**Coverage audit (all verified programmatically against SCAFFOLD.yaml):**
- **Entities:** all 15 entities' fields — 188 required identifiers (entity fields + endpoint inputs + path params + common fields) — all present verbatim in backticks; `study_id` was the one initial miss, added to §3.7.
- **State machines:** all 13 machines (incl. dual-dimension SoundInsulationApplication A/B and Complainant auto-transitions) walked transition-by-transition in §3; every enum/state value from the scaffold verified present.
- **Calculations:** all 11 expressed as precise prose with pinned evaluation orders, inclusive/exclusive boundaries, and both scaffold worked examples (1,111,115¢ → 1,277,783¢ grant split; 34.5 → 40.5 stays `MODERATE` annoyance index); constants embedded (300s/1200s windows, 43,200 min, 86,400 s, caps, multipliers).
- **Validations:** all 13 priority groups rendered as an explicit ordered gate list in §2.11 plus trigger-context prose in §3; all 61 error IDs appear in §2/§3 narrative (not just §5).
- **Endpoints:** all 99 in §4 table with scaffold roles; side effects (cascades A–D, counter maintenance, auto-notifications at crossing thresholds 5 and 3, lazy offer sweep) expressed in §3.
- **Errors:** §5 table matches scaffold exactly — 61 IDs, correct HTTP statuses (set symmetric difference empty).
- **Roles:** all 7 named with exact spelling; identity semantics translated per role.
- **Contract 3 (§3 path purity):** 810 backticked tokens scanned, 0 path/method violations.
- §2.2 emitted byte-identically; no audit footer in the PRD.

## RESUME ASSESSMENT — 2026-08-14T04:21:02.000Z

Previous run terminated mid-flight after Steps 5/6 subagents wrote their files but before the orchestrator logged their summaries. On-disk audit at resume:

- **Steps 1–4: COMPLETE** — all three scaffold yamls present and lint-clean (per Step 2 entry above); `workspace/INSTRUCTION.md` copied; `workspace/PRD.md` present (427 lines per Step 4 entry).
- **Step 6 (implementation): COMPLETE** — `workspace/implementation/` has app.py + 11 route modules + services/serialize/validate/middleware/db/util/response/errors + start.sh + requirements.txt; every file py_compiles; Flask url_map shows all ~99 scaffold endpoints registered under `/noise-program` (plus `/_clock` system endpoints); cold boot via `start.sh` succeeds.
- **Step 5 (tests): PARTIAL — truncated mid-generation.** 66 test functions across test_01–test_08, all py_compile-clean, every test carrying exactly one valid `Design:` tag pointing at a real design-index instance (verified programmatically: zero dangling tags). BUT coverage stops at 13/26 non-stub §1.8 difficulty instances (each covered by exactly 2 tests) and 40/58 non-stub §1.9 corner instances. The 3 corner `excluded_because` stubs legitimately have no tests. Truncation (not deliberate PRD-first skips) is confirmed by the gap list containing instances whose worked examples the Step 4 entry explicitly verified as embedded in PRD prose (`grant_split_round_per_component_then_sum_pinned` 1,111,115¢→1,277,783¢; `annoyance_tier_keyed_on_base_index_only` 34.5→40.5 MODERATE) — those could never have failed the PRD-first filter.
- **Uncovered §1.8 instances (13):** annoyance_tier_keyed_on_base_index_only, curfew_closed_intervals_touching_minutes_conflict, curfew_score_tiered_engine_weights_and_grace_band, fund_conservation_across_issue_decline_reissue_disburse, grant_provisional_vs_final_obligation_reconciled, grant_split_round_per_component_then_sum_pinned, issue_offer_gated_by_study_adoption, outage_half_open_intervals_adjacency_allowed, referential_beats_fiscal_on_issue_offer, repeat_standing_threshold_9_vs_10_complaints, report_patch_missing_auth_beats_not_found, report_revision_loop_then_publish, report_submit_gated_by_unclassified_events_in_period.
- **Uncovered active §1.9 instances (18):** complaint_create_with_unknown_complainant_returns_not_found, complaint_filed_into_published_quarter_rejected, compliance_score_uses_probation_multiplier, entity_backed_ownership_violations_forbidden, flight_patch_after_operated_rejected, manual_outreach_for_good_standing_rejected, occ_stale_fund_version_on_issue_offer_rejected, occ_stale_report_patch_rejected, outreach_case_full_lifecycle_resets_standing, priority_score_exact_weight_sum, quarterly_rollup_excludes_records_at_period_end, rbac_entity_backed_positive_reads, rbac_exclusive_operation_denials, request_missing_auth_headers_returns_unauthenticated, segregation_of_duties_self_approve_forbidden, shape_violation_invalid_payload_beats_role_check, uniqueness_constraint_violations_rejected, wrong_role_with_valid_payload_returns_unauthorized.

Resume plan: keep Steps 2/3/4/6 artifacts and the existing 66 tests; run a Step 5-completion subagent for the 31 uncovered non-stub instances; then Steps 7→9 as normal.

## Step 6: Generate Implementation — 2026-08-14T04:21:02.000Z (verified at resume; original subagent summary lost)

Implementation generation completed in the previous run (files written 2026-08-14T03:52–04:15); the orchestrator was terminated before logging the subagent's summary. Resume-time verification (documented in RESUME ASSESSMENT above): all 12 source files py_compile; Flask url_map registers all ~99 scaffold endpoints plus `/_clock` system routes; `start.sh` cold-boots cleanly. Artifact judged complete and reused as-is.

## Step 5: Generate Unit Tests — 2026-08-14T04:48:05.000Z (completed at resume; original run truncated)

Original Step 5 run was truncated mid-flight (66 tests, 13/26 §1.8 + 40/58 active §1.9 instances). A completion subagent generated the remaining 31 uncovered non-stub instances. Verbatim summary of the completion subagent:

All verification passed. Final summary:

## Files created (6 new; test_01–08, conftest.py, and test_helpers/ untouched)

- `test_suite/test_09_insulation_grants_and_ledger.py` (7 tests) — grant split rounding, provisional/final reconciliation, ledger conservation, priority score
- `test_suite/test_10_offer_gates_and_fund_occ.py` (5 tests) — study-adoption gate, referential-beats-fiscal ordering, fund OCC
- `test_suite/test_11_curfew_and_annoyance.py` (7 tests) — curfew flags/score tiers, probation multiplier, closed-interval conflicts, annoyance tier keying
- `test_suite/test_12_reports_and_quarter_lock.py` (10 tests) — revision loop, submit gate, auth-before-existence, report OCC, rollup boundary, quarter lock, segregation of duties
- `test_suite/test_13_standing_outreach_and_intervals.py` (7 tests) — 9-vs-10 threshold, outreach lifecycle, manual-case guard, outage half-open adjacency, flight terminal lockdown
- `test_suite/test_14_rbac_and_validation_ordering.py` (8 tests) — auth/role/shape gates, FK existence, uniqueness battery, entity-backed ownership, RBAC denials/positive reads

## Per-instance disposition: all 31 TESTED (44 new tests), zero skips

Every instance had verbatim PRD coverage and uniquely-derivable outcomes. 13 difficulty instances × 2 tests, 18 corner instances × 1 test. Five PRD-fidelity adjustments were made where the design yaml conflicted with PRD prose (assertions follow the PRD, which is the contract):

1. **`priority_score_exact_weight_sum`** — asserted `priority_score == 105` (PRD §3.8: 80 band-75 + 20 HOSPITAL + 0 no-complainant + 5 rooms≥8). The yaml's precomputed literal `115` is an arithmetic slip no PRD-faithful implementation can produce (scaffold constants confirm 80/20/10/5).
2. **`curfew_score_tiered_engine_weights_and_grace_band`** — the yaml's `setup_api_calls` put F3 at 22:34 (minute 1354, inside the violation interior [1335,1424]) while its own `distinguishing_aspect` says "minute 1334 in grace -> movement but not violation". Used 22:14 (minute 1334) so the movement-only outcome is PRD-derivable; all asserted values (movements 3, violations 2, score 800.0, WATCH) match the yaml.
3. **`uniqueness_constraint_violations_rejected`** — exercised `ERR_DUPLICATE_FISCAL_YEAR_FUND` after closing the ACTIVE fund, so each of the five uniqueness rules is isolated (PRD states no ordering between duplicate-FY and single-ACTIVE when both fire — per the validation-priority silence pattern).
4. **`fund_conservation_across_issue_decline_reissue_disburse`** — asserted the post-decline `UNFUNDED` state via GET rather than the decline response body (PRD's "immediately re-queues ... within the same request" leaves the response-body state two-reader ambiguous; the fund buckets and successful re-issue are pinned and asserted).
5. **`outreach_case_full_lifecycle_resets_standing`** — advanced the clock to 2026-08-02 after filing so `repeat_baseline_at` is strictly after every filing's `created_at`; otherwise `complaints_90d == 0` is not uniquely derivable (filings at the identical instant would count under PRD's "at or after the baseline"). Also strengthened `report_submit_gated` (b) with `events_aircraft_count == 0` (the event lands VERIFIED, which the live formula counts — only a frozen snapshot reads 0).

## Verification results

- **py_compile**: all 6 files compile; all 6 import cleanly with `test_helpers` on PYTHONPATH.
- **Tag validation**: every test function in the suite has exactly one `Design:` tag; zero dangling tags; no `excluded_because` stub is tagged.
- **Citation verbatim check**: 89 quoted spans in the new docstrings — all survive literal grep of PRD.md (whitespace-normalized).
- **Coverage cross-check**: §1.8 **26/26** difficulty instances (each with exactly 2 tests); §1.9 **58/58** active corner instances (+3 stubs correctly excluded); total suite 110 tests (66 existing + 44 new).

## Helper extensions

None required — all preconditions were constructible with the existing factories/fixtures (`setup_decided_application`, `setup_grant_committed`, `setup_adopted_study_with_parcel`, `setup_repeat_complainant`, `publish_report`, `create_report`, etc.).

## Step 7: Run Tests and Iterate — 2026-08-14T05:04:25.000Z

All 8 rounds are clean: **110/110 passed in every round**. Exit condition met.

---

## Summary

**Iterations run:** 2 (plus one voided sweep caused by a harness invocation error on my side — I initially passed `--start-command "bash start.sh"` without the `cd <abs-path> &&` prefix; the runner's pytest plugin resolves a relative start directory against the pytest subprocess's cwd (the test_suite dir), so every per-test server respawn died with `bash: start.sh: No such file or directory`. Not a test or implementation defect; fixed by using the prescribed command form.)

**Round-1 diagnostic outcome:** 107/110 in all 8 rounds — a deterministic 3-test failure set, zero flakiness:
- `test_08_insulation_funds_and_offers.py::test_fund_close_with_reserved_rejected`
- `test_08_insulation_funds_and_offers.py::test_offer_auto_expiry_on_read_releases_reservation`
- `test_08_insulation_funds_and_offers.py::test_offer_accept_after_expiry_returns_offer_expired`

All three died on `NameError: name 'setup_issued_offer' is not defined`.

**Tests deleted:** None.

**Fixes applied to `test_helpers/`:** None needed — the helpers were correct; the bug was in the test file's import list.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1614_airport_noise_complaint_abatement_program/test_suite/test_08_insulation_funds_and_offers.py` — added `setup_issued_offer` to the `from test_helpers import (...)` tuple. The three failing tests call this fixture (defined in `test_helpers/fixtures.py` and re-exported through the package barrel) but the name was omitted from the file's explicit import list. STEP 1 verification: all three tests assert rules verbatim-covered by PRD §3.8 / §2.4 (`ERR_FUND_HAS_RESERVED` on close-with-reserved; lazy offer expiry retracting `OFFER_ISSUED`→`UNFUNDED` on read with 45-day expiry; `ERR_OFFER_EXPIRED` at/after expiry) and uniquely derivable (pinned grant split 500,000¢ TIER2 → 460,000¢ reserved; expiry 2026-08-01 + 45d = 2026-09-15). A follow-up AST scan of all 14 test files confirmed no other missing helper imports.

**Fixes applied to `implementation/`:** None — the implementation was already PRD-faithful; every non-import failure path (cascades A–D, OCC guards, pinned rounding, gate ordering) passed consistently once the fixture name resolved.

**Verification:** Final 8-round parallel sweep under `--isolation per-test-server`: every round `passed=110 total=110 failed=0 errors=0 skipped=0` (~148s/round).

## Step 8: Finalize PRD — 2026-08-14T05:07:25.000Z

PRD_FINALIZED.md is written at `/home/ubuntu/github/CodingPRD/tasks/task_1614_airport_noise_complaint_abatement_program/workspace/PRD_FINALIZED.md` as an exact copy of PRD.md. Zero edits were made — the single Step 7 fix (adding `setup_issued_offer` to a test file's import list) is a pure Python name-resolution bug with no PRD semantics, and all three rules it exercised are already verbatim-pinned in PRD.md and behaviorally matched by `implementation/`.

## Line counts and delta

- `PRD.md`: 427 lines; `PRD_FINALIZED.md`: 427 lines; 0% delta (diff confirms byte-identical).

## Changes

None.

## Verification evidence (in lieu of per-edit search logs, since no edits were made)

**Rule 1 — ERR_FUND_HAS_RESERVED close guard.** PRD §3.8 (PRD.md:229): "A `NoiseOfficeAdmin` may close an `ACTIVE` fund, moving it to `CLOSED`, only when `reserved_cents` is exactly zero (else `ERR_FUND_HAS_RESERVED`); operations that require an active fund against a closed one are rejected with `ERR_INVALID_FUND_STATE`." Implementation: `implementation/routes/funds.py:151-155` — guards `status != "ACTIVE"` → `ERR_INVALID_FUND_STATE`, then `reserved_cents != 0` → `ERR_FUND_HAS_RESERVED`. Error catalog agrees at 409 (PRD.md:403; errors.py:54). Exact match.

**Rule 2 — lazy offer expiry, 45-day window, OFFER_ISSUED→UNFUNDED retraction on read.** PRD §2.4 (PRD.md:80): "Offer expirations are deliberately not swept by the clock. An expired offer is retracted lazily — only when the application holding it is next read, whether individually or through a list." PRD §3.8 (PRD.md:239): "computes `offer_expires_at` as exactly 45 days after issuance". PRD §3.8 (PRD.md:243): "any read of an application whose `offer_expires_at` has passed moves it from `OFFER_ISSUED` back to `UNFUNDED`, stamps `last_offer_expired_at`, and releases the reservation back to available (bumping the fund's `version`)". Implementation: `services.py:446` sets `offer_expires_at = t + timedelta(days=45)` (2026-08-01 + 45d = 2026-09-15, as the test asserts); `services.py:462-472` `sweep_offer_expiry` retracts to `UNFUNDED`, stamps `last_offer_expired_at`, and calls `release_reservation` (services.py:451-459, which decrements `reserved_cents` and `touch(fund)` bumps the fund version); the sweep fires on both read paths — list (`routes/funds.py:237`) and single get (`routes/funds.py:258`) — and the clock-advance handler (`routes/reports.py:188-197`) fires only `sweep_notifications_globally()`, never an offer sweep. Exact match on every clause.

**Rule 3 — ERR_OFFER_EXPIRED on accept at/after expiry.** PRD §3.8 (PRD.md:243): "Accepting the offer moves `OFFER_ISSUED` to `GRANT_COMMITTED` and is only valid strictly before `offer_expires_at`; at or after expiry the request is rejected with `ERR_OFFER_EXPIRED`." Implementation: `routes/funds.py:387-393` — guard `funding_status != "OFFER_ISSUED"` → `ERR_INVALID_APPLICATION_STATE`, then `if now() >= a["offer_expires_at"]: raise err("ERR_OFFER_EXPIRED", ...)` ("strictly before" valid, "at or after" rejected). The write path deliberately does not pre-sweep (comment at funds.py:390-391: "expiry is evaluated lazily on READ only; a write on an expired-but-unswept offer deterministically fails"), which is precisely what makes `ERR_OFFER_EXPIRED` — rather than `ERR_INVALID_APPLICATION_STATE` — observable on an expired-but-unread offer, matching the PRD's pinned error. Error catalog agrees at 409 (PRD.md:391; errors.py:42). Exact match.

The adjacent sentence in PRD.md:243 ("the auto-expire sweep fires first...") describes the read-path lazy sweep (§2.4 cross-reference), which the implementation exhibits verbatim on both read endpoints; the accept-path error ordering is separately and explicitly pinned by the `ERR_OFFER_EXPIRED` clause, so no wording change was warranted.

## Step 9: Complete PRD — 2026-08-14T05:22:15.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1614_airport_noise_complaint_abatement_program/workspace/PRD_COMPLETED.md` is produced — a minimal in-paragraph patch over PRD_FINALIZED.md, fully aligned to `implementation/`. Heading structure is unchanged (diff of all `^#` lines is empty); only paragraph text and one endpoint-table row changed.

**Source vs output:** PRD_FINALIZED.md 427 lines / 80,646 chars → PRD_COMPLETED.md 430 lines / 86,236 chars (char-delta +5,590).

**Counts:** 35 ambiguity-pins, 4 mismatch-revisions (39 change sites total; one site mixes both).

Changes (section — insert|revise — ambiguity|mismatch — what — impl site):

- §2.2 — insert — ambiguity — unmatched route/method answered with ERR_NOT_FOUND 404 envelope; trailing slash tolerated — app.py:22,39-48
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit` or negative/non-integer `offset` rejected ERR_VALIDATION — validate.py:79-103
- §2.3 — insert — ambiguity — `has_more` true exactly when offset + returned page size < `total_count` — response.py:22-30
- §2.4 — insert — ambiguity — current logical time readable via GET /_clock/current_utc for any authenticated role — routes/reports.py:200-204
- §2.5 — insert — ambiguity — `version` reads 1 and `updated_at` equals `created_at` on freshly created resources — services.py:31-34, e.g. routes/complainants.py:57-59
- §2.10 — revise — mismatch — path-existence (gate 6) runs after shape and role gates; replaced "before the outage payload is ever considered" — routes/monitors.py:88-101
- §2.11 gate 2 — insert — ambiguity — supplied `grace_minutes` must be ≥ 0; unparseable/non-object JSON body is a shape failure — routes/curfew.py:47, middleware.py:52-65
- §3.1 — revise+insert — mismatch+ambiguity — "two-to-three-letter" → "two-to-three-character"; out-of-range `iata_code` length → ERR_VALIDATION — routes/flights.py:177-178
- §3.1 — insert — ambiguity — operator list supports `compliance_standing` filter — routes/flights.py:209-212
- §3.2 — insert — ambiguity — unresolvable `operator_id` on flight creation → ERR_OPERATOR_NOT_FOUND — routes/flights.py:61-63
- §3.2 — insert — ambiguity — `status` SCHEDULED in flight update → ERR_VALIDATION; exemption-only update legal while SCHEDULED; no-op update does not bump version — routes/flights.py:140-162
- §3.2 — insert — ambiguity — compliance-summary `quarter` param required, must match YYYY-Qn (else ERR_VALIDATION) — routes/flights.py:259-262
- §3.2 — insert — ambiguity — flight-list `quarter` filter keys `actual_at` for OPERATED, else `scheduled_at` — routes/flights.py:38-41,108-109
- §3.3 — insert — ambiguity — outages recordable against a monitor in any status, including DECOMMISSIONED — routes/monitors.py:88-119
- §3.3 — revise — mismatch — `uptime_pct_30d` recomputed against the current logical clock on every read/consult, not only when an outage is recorded — services.py:295-308, serialize.py:107
- §3.3 — insert — ambiguity — AIRCRAFT classification omitting `flight_id` → ERR_VALIDATION; unresolvable `flight_id` on MIXED → ERR_FLIGHT_NOT_FOUND — routes/events.py:121-138
- §3.3 — insert — ambiguity — cascade-B auto-draft pinned: DRAFT/ADVISORY, `noise_event_id` set, no `complaint_id`, exact subject/body strings — routes/events.py:29-56,160-162
- §3.3 — insert — ambiguity — reclassification also resets `classification_confidence` to 0 and clears `classification_basis` — routes/events.py:216-225
- §3.3 — insert — ambiguity — DNL `date` query param required, YYYY-MM-DD (else ERR_VALIDATION) — routes/monitors.py:202-204
- §3.4 — insert — ambiguity — provide-info narrative joined to existing narrative by a single newline — routes/complaints.py:200-202
- §3.4 — insert — ambiguity — event-only correlation records `correlation_variant_used` RELAXED — services.py:146-149
- §3.4 — insert — ambiguity — complaint-threshold auto-draft pinned: DRAFT/ADVISORY, links complaint (and correlated event when present), exact subject/body — routes/complaints.py:46-73,267-274
- §3.4 — insert — ambiguity — unsubstantiated close from CORRELATED clears both correlation id fields while confidence/variant remain — routes/complaints.py:300-315
- §3.4 — insert — ambiguity — reopen window boundary inclusive (exactly 30 days allowed); prior `closure_outcome` retained — routes/complaints.py:334-342
- §3.4 — insert — ambiguity — complaint-list `quarter` filter keys on `created_at` — routes/complaints.py:139-140
- §3.5 — insert — ambiguity — unresolvable `complaint_id` on notification draft → ERR_NOT_FOUND — routes/notifications.py:67-71
- §3.5 — insert — ambiguity — close from RESPONSE_RECEIVED records `closed_outcome` RESOLVED regardless of any supplied value — routes/notifications.py:226-227
- §3.5 — insert — ambiguity — automatic escalation records reason "Response deadline exceeded (auto-escalated)" — services.py:506-515
- §3.5 — insert — ambiguity — escalated close with no response and no OVERRIDE → ERR_INVALID_NOTIFICATION_STATE; with response, omitted outcome defaults RESOLVED; complaint-terminal check evaluated first — routes/notifications.py:213-225
- §3.6 — insert — ambiguity — manual case creation accepts any declared `trigger_reason` — routes/outreach.py:30-33
- §3.6 — insert — ambiguity — annoyance trailing windows boundary-inclusive; undeclared zone computes to base 0.0 / LOW / final 0.0 — services.py:598-634
- §3.7 — insert — ambiguity — cascade A hop one also stamps `reassessed_at` and increments each parcel's version — routes/studies.py:169-177, services.py:355-357
- §3.7 — insert — ambiguity — duplicate `parcel_ref` within study → ERR_VALIDATION; parcels addable in any study status — routes/studies.py:207-223
- §3.8 — insert — ambiguity — fund list supports `status` filter — routes/funds.py:90-93
- §3.8 — revise — mismatch — withdrawal returns funding to UNFUNDED only for OFFER_ISSUED/GRANT_COMMITTED; a REIMBURSED application keeps REIMBURSED and moves no money — routes/funds.py:450-453
- §3.8 — insert — ambiguity — disbursement releases the whole provisional reservation and moves the final total into disbursed; a final total larger than the reservation is unguarded and draws available down — routes/funds.py:425-437
- §3.9 — insert — ambiguity — report edit: DRAFT-state check precedes the stale-version check; a notes-less edit changes nothing and does not bump version — routes/reports.py:96-104
- §4 — insert (table row) — ambiguity — GET /_clock/current_utc row, all seven roles — routes/reports.py:200-204

Cross-checks: the §5 error catalogue matches `implementation/errors.py` exactly (61 ids, identical HTTP statuses). Behaviors probed but left unchanged because the PRD already pins the impl's choice: §2.11 gate ordering (impl follows it everywhere, including verify's uptime-before-confidence and issue-offer's state→OCC→study→fund sequence), the offer-expiry lazy sweep firing only on reads while accept on an unswept expired offer yields ERR_OFFER_EXPIRED, and the strict-greater-than overdue definition for auto-escalation.
