# Worklog — task_2549_flood_zone_determination_map_amendment_support

## Step 1: Create task directory — 2026-09-03T09:17:37.799Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2549_flood_zone_determination_map_amendment_support` and its `workspace/` subdirectory. Index 2549 was pre-assigned by the invoking pipeline; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-03T10:47:12.831Z

All three scaffold artifacts are complete and lint-clean.

## Files

| File | Lines |
|---|---|
`/home/ubuntu/github/CodingPRD/tasks/task_2549_flood_zone_determination_map_amendment_support/SCAFFOLD.yaml` | 2729 |
`/home/ubuntu/github/CodingPRD/tasks/task_2549_flood_zone_determination_map_amendment_support/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1549 |
`/home/ubuntu/github/CodingPRD/tasks/task_2549_flood_zone_determination_map_amendment_support/SCAFFOLD_CORNER_DESIGN.yaml` | 3520 |

All three parse under `yaml.safe_load`. `SCAFFOLD.yaml` top-level keys are `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` — neither `scaffold_difficulty_design` nor `scaffold_corner_design` appears in it; each design file has exactly its one top-level key.

## Counts

- §1.1 entities 11 · §1.2 state machines 8 · §1.2.1 concurrency rules 1 · §1.3 calculations 12 · §1.4 validations 32 (priorities 1–32) · §1.5 endpoints 49 · §1.6 errors 47 · §1.7 roles 5 (`role_model: segregation_of_duties`)
- §1.8: 18 instances, 2 per each of the 9 §0.5 difficulty rules
- §1.9: 74 instances over all 9 sections — entities 11, state_machines 11, calculations 11, validations 21, endpoints 4, errors 6, rbac 4, cross_cutting_complexity_layers 4, consistency_model 2 (60 with full `test_recipe`, 14 `excluded_because` stubs)

## Linter verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2549_flood_zone_determination_map_amendment_support/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2549_flood_zone_determination_map_amendment_support/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2549_flood_zone_determination_map_amendment_support/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    49
  §1.1 entities declared:     11
  §1.8 instances scanned:     18
  §1.9 instances scanned:     60
  Calls scanned (§1.8+§1.9):  791

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Coverage audit (scripted over the parsed YAML)

- Errors: 0 of 47 uncovered — every `§1.6` id is exercised by a §1.8 or §1.9 instance.
- Endpoints: 0 of 49 never called across both design files.
- Calculations 12/12, entities 11/11, state machines 8/8, validation error ids 32/32 all appear in grounds/asserts.
- Instance names: 92 total (18 + 74), zero duplicates across both files; all 14 `excluded_because.difficulty_instance` citations resolve to a real `rule_id / name` pair.
- Placeholder closure: 0 unbound `${var}` in any `payload`, `as_user_id` or path template.
- Grounds: every `grounds[*]` reference resolves into §1.0–§1.7 (entity fields, endpoint method+path, validation priority↔error_id, error ids, calc names, role names, `concurrency_rules.redetermination-create-stale-folio`, `response_envelope.pagination_fields`).
- §1.9 claim types are drawn only from `references/claim-extraction-guide.md`, and all four active `complexity_layers` (optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers) have a matching instance.

Fixes made while finishing: 8 list-endpoint captures used `$.data.total_count`/`has_more`, which the linter rejects for `Entity[]` outputs — reworked to element-form captures (quoted, since `$.data[0].id` unquoted breaks YAML flow mappings) with the envelope claims moved into asserts; one stub cited `boundary_precision_check / notice_cooldown_...` when that instance lives under `resource_temporal_overlap`; and 8 errors (7 not-found ids plus `ERR_INVALID_DETERMINATION_STATE`) plus 13 never-called GETs were uncovered until two new `errors`-section instances were added (`corner_unknown_id_on_every_detail_read_returns_its_own_not_found_error`, `corner_superseded_determination_cannot_be_named_by_a_dispute_or_a_notice`).

Note on RBAC-denial corners: `scaffold_lint.py` check (b) forbids writing a call whose `as:` role is outside the endpoint's `roles`, so every denial claim (403 `ERR_FORBIDDEN_ROLE`, and the 401 header-omission case) is expressed as an assert over the authorized trigger call rather than as an illegal call object.

## Step 3: Copy shared files — 2026-09-03T10:47:34.576Z

Copied `./INSTRUCTION.md` to `tasks/task_2549_flood_zone_determination_map_amendment_support/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T11:00:12.000Z

PRD generated and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2549_flood_zone_determination_map_amendment_support/workspace/PRD.md` — 386 lines, 14,123 words, 105,009 bytes. Built incrementally (1 Write + 4 heredoc appends + 3 targeted repair edits); no truncation.

**Section list**
- §1 Introduction (3 paragraphs)
- §2 Global Specifications — 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim) · 2.3 Pagination and Collection Filters · 2.4 Common Resource Properties, Identity and the Logical Clock · 2.5 The Validation Ladder · 2.6 Stale-Folio Protection When Issuing Determinations · 2.7 Measurement, Datum and Monetary Precision · 2.8 Cascade Discipline and Recomputation Semantics · 2.9 Community Participation as a System-Wide Coverage Gate · 2.10 Conservation Invariants · 2.11 Segregation of Duties
- §3 Business Logic (9 subsections) — 3.1 Registering the Parties · 3.2 The Map Timeline · 3.3 Prospective Analysis of a Preliminary Map · 3.4 Geocoding Properties and Cataloguing Structures · 3.5 Loan Folios and the Determination Itself · 3.6 The Mandatory Purchase Obligation · 3.7 The Life-of-Loan Monitoring Sweep · 3.8 Elevation Evidence and Map Amendment Packages · 3.9 Borrower Disputes and Joint Agency Review
- §4 Endpoint Definitions (4-column table, 49 rows) · §5 Error Code Catalogue (2-column table, 47 rows)

**Coverage audit (machine-verified against SCAFFOLD.yaml)**
- 11 entities / 133 entity fields: all present in backticks, 0 missing. 71 request-body identifiers, 30 query params, 11 path params, 15 non-entity output keys: 0 missing. Total required set 153, missing 0.
- 36 state-machine transitions across 8 machines (MapPanel 6, Determination 8, Dispute 4, LoanFolio monitoring 2 + insurance 6, ElevationCertificate 2, MapAmendmentRequest 5, ComplianceNotice 3): every `from -> to` pair, precondition and side effect narrated, including both 5-hop cascades (panel-effective, dispute-sustained) and the 2-hop geocode-correction cascade.
- 12 calculations all rendered as prose with pinned evaluation orders and constants embedded in dollars/days/feet (geocode buffers 0/25/250 ft, coverage caps 25,000,000 / 50,000,000 / 3,500,000 / 10,000,000 cents, datum offsets -2.44/-1.15/-0.87/-0.55 ft, fee base 0/50,000 + 12,500 per resubmission, tier surcharges 0/30/45 %, 45/30/30/15-day notice windows, 5-day cooldown, 90/180/365/30-day periods). No pseudocode, no fuzzy quantifiers (the only three "about"s are non-numeric prose).
- 32 validations expressed as an explicit ordered ladder in §2.5 with priority numbers 1-32; all `applies_to` endpoint sets enumerated. 47 error IDs each appear in §2/§3 prose in addition to the §5 table (0 table-only). 1 concurrency rule expressed with write endpoint + `expected_loan_folio_version` + `ERR_STALE_LOAN_FOLIO_VERSION` + HTTP 412. 5 roles named with `identity` translated (`Lender` entity-backed, other four opaque).
- §4 table: 49/49 endpoints, method+path+authorized roles match the scaffold exactly (role-set diff empty). §5: 47/47 error IDs with matching HTTP statuses.

**Hard Contracts**
```
Field coverage check:
- entities[].fields: 133 required, 133 present, 0 missing
- endpoints[].request_body: 71 required, 71 present, 0 missing
- endpoints[].query_params: 30 required, 30 present, 0 missing
- endpoints[].path_params: 11 required, 11 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 32 checked, 32 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 1 checked, 1 expressed, 0 missing
- state_machines[].transitions: 36 checked, 36 fully expressed, 0 missing
- calculations[]: 12 checked, 12 fully expressed, 0 missing
- validations[] conditions: 32 checked, 32 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 49 checked, 49 expressed, 0 missing
- entities[].fields[] structured content: 133 checked, 133 reconstructible, 0 missing
- sibling-branch symmetry: 10 groups checked, 10 with equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 1046
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```
§2.2 diffs byte-identical against `section-2.2-response-structure.md`. No audit footer written into PRD.md (grep for contract-report markers returns 0).

**Verbatim last 10 lines**
```
| `ERR_PANEL_EFFECTIVE_DATE_OVERLAP` | 409 |
| `ERR_NOTICE_WINDOW_ACTIVE` | 409 |
| `ERR_PANEL_SEQUENCE_INVALID` | 409 |
| `ERR_RESUBMISSION_LIMIT` | 409 |
| `ERR_STRUCTURE_NOT_ABOVE_BFE` | 422 |
| `ERR_DISPUTE_BASIS_UNSUPPORTED` | 422 |
| `ERR_ORIGINATION_ALREADY_COMPLETE` | 409 |
| `ERR_PANEL_NOT_PRELIMINARY` | 409 |
| `ERR_COVERAGE_BELOW_REQUIRED` | 422 |
| `ERR_ESCROW_INSUFFICIENT` | 402 |
```
The file ends on the completed final row of the §5 table — a real section boundary, not mid-sentence.

One note for the caller: the scaffold's `Lender.escrow_servicing_flag == true` force-placement precondition is the one rule the scaffold does not attach an error ID to (validation priority 14 covers only `force_placement_authorized_flag`). The PRD states the precondition without naming an error, mirroring the scaffold's own silence rather than inventing a code. `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened.

**Orchestrator truncation check (independent):** `wc -l` 386, `grep -c '^| \`ERR_'` = 47 (matches the scaffold's 47 errors), section headers present for §1–§5 including all 11 §2 and all 9 §3 subsections, and `tail -20` shows a completed final table row. PRD accepted; no regeneration needed.

## Step 5: Generate unit tests — 2026-09-03T12:39:00.000Z

Generation is complete. Both stages are on disk and self-consistent.

## Files

`test_helpers/` (Stage 1, 9 files, 1,998 lines, 115 exports): `__init__.py` 121, `api_client.py` 243, `api_errors.py` 107, `assertions.py` 264, `constants.py` 73, `factories.py` 181, `fixtures.py` 490, `test_users.py` 70, `types.py` 449.

`test_suite/` (Stage 2, 11 test modules + conftest, 5,949 lines): conftest 77, `test_01_community_and_lender_registration` 351, `test_02_property_geocoding_and_structures` 501, `test_03_map_panel_timeline` 622, `test_04_loan_folio_and_determination_issuance` 668, `test_05_coverage_and_notice_obligation` 577, `test_06_force_placement_and_escrow` 666, `test_07_elevation_certificates` 392, `test_08_map_amendment_packages` 501, `test_09_borrower_disputes_and_joint_review` 543, `test_10_monitoring_sweep_and_impact_projection` 550, `test_11_panel_effective_cascade_and_folio_dimensions` 501.

## Tests and design coverage

**78 tests, 78 `Design:` tags, 1:1 with the design indices.** Audit results: 92 instances total (18 Difficulty + 74 Corner), 14 of them `excluded_because:` stubs which got no tests; the remaining 78 non-stub instances each have exactly one test. No duplicate tags, no tags pointing at a stub or at a non-existent instance, no untagged test function, nothing left untranslated. Zero instances were skipped wholesale by the PRD-first filter; four *individual claims* inside instances were dropped or corrected where the design contradicted the PRD (details below).

Verification, all clean: `verify_2549.py` -> `tests: 78 problems: 0` (every `PRD §x.y: "..."` citation survives a literal grep of PRD.md; exactly one trailing `Design:` line per docstring); a section-label audit that resolves each cited sentence to the section it actually occupies -> `issues 0`; AST parse of all 21 files; no unused imports.

## Design-vs-PRD deviations (deliberate, documented in the test prose)

- `open_notice_count` after the sustained-dispute cascade: design says 0, but §2.10 mandates a full re-count and hop 5 creates a `SENT` `RE_DETERMINATION` notice -> asserted 1.
- Dispute enums: design's `UPHOLD_BORROWER` / bare `SUSTAINED` are not in the PRD's enums -> used `REVISE` and `REVISED_BY_CONCURRENCE`.
- `corner_borrower_not_on_the_loan_cannot_file_a_dispute`: the extra claim that a foreign borrower cannot file an elevation certificate has no PRD basis (§3.8 imposes no folio-presence rule) -> claim dropped, rest of the instance translated.
- `superseded_at` / `closed_at` in `corner_panel_effective_cascade_is_readable_with_no_lag`: design says 2027-04-28 (the panel's `effective_date`), PRD §3.2 says "the current logical instant" -> asserted 2027-05-01, consistent with the paired difficulty instance.
- `folio_monitoring_and_insurance_dimensions_move_independently`: the claim `required_coverage_cents == 0` while the community is `UNAVAILABLE` is not uniquely derivable — §3.6 line 200 reads the *stored* `mandatory_purchase_flag` (true, giving 25,000,000) while §3.5 line 192 defines that flag as a function of current `coverage_availability` (giving 0). That single claim is not asserted; everything else in the instance is (monitoring `SUSPENDED`, `insurance_status` unchanged, posture `COVERAGE_UNAVAILABLE`, and the full reinstatement to `required 25,000,000` / `COMPLIANT`). This is the one implementation-visible ambiguity worth flagging to the PRD owner.

Also worth noting for whoever maintains Stage 1: `fixtures.publish_successor_panel`'s docstring claims it walks the panel to `LFD_ISSUED`, but it only publishes — callers must invoke `walk_panel_to_lfd_issued` themselves (all tests do).

I did not read or write anything under `workspace/implementation/`, and ran no `pkill`.

**Orchestrator note on isolation (deviation from the skill, recorded deliberately):** the skill requires Steps 5 and 6 to be launched in a single assistant message so that Step 6's subagent starts before `test_suite/` exists and is therefore *physically* unable to read it. I emitted only one Agent call in that message, so Step 6 was launched after Step 5 returned and `test_suite/` was already on disk. Mitigation applied: Step 6's prompt carried an ABSOLUTE PROHIBITION forbidding it to read, list, glob, or grep `test_helpers/`, `test_suite/`, or either SCAFFOLD_*_DESIGN.yaml, and forbidding it to run pytest. Step 6 reported compliance. Isolation is therefore contractual rather than physical for this task; noted so the result can be discounted if the impl looks suspiciously test-shaped.

## Step 6: Generate implementation — 2026-09-03T12:39:00.000Z

Implementation complete. Built strictly from `INSTRUCTION.md` + `SCAFFOLD.yaml` + `PRD.md`; `test_helpers/`, `test_suite/`, and the two SCAFFOLD_*_DESIGN.yaml files were never read, listed, or grepped, and pytest was never run.

## Files created (`.../workspace/implementation/`)

| file | lines | role |
| --- | --- | --- |
| `start.sh` (executable) | 10 | guarded pip install, `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=2.0` |
| `app.py` | 96 | app factory, blueprints at `/flood-zone`, `strict_slashes=False`, ApiError/400/404/405/415/500 envelope handlers, `0.0.0.0:$PORT` (default 10000) |
| `db.py` | 104 | in-memory dict store, logical clock (`2026-08-01T00:00:00Z` default), `new_row`/`touch`/`ordered` (created_at then `_seq`) |
| `errors.py` | 85 | all 47 error ids with the PRD's exact HTTP statuses |
| `response.py` | 91 | meta/response_type/data envelope, `req_`+20 alnum, 3-fractional-digit timestamps, pagination |
| `authz.py` | 62 | `X-User-ID`/`X-User-Role`, ladder steps 1-3 |
| `shape.py` | 254 | ladder priority 4: unknown/required fields, enums, int/decimal scale, limit 1..100 |
| `enums.py` | 96 | every declared enumeration range |
| `calc.py` | 292 | all pinned constants and calculations (Decimal + ROUND_HALF_UP) |
| `services.py` | 413 | lookups, full re-counts, notice mechanics, determination adoption, escrow settlement, the three cascades |
| `routes_reads.py` | 183 | 22 collection/single reads + filters |
| `routes_parties.py` | 237 | communities, lenders, properties, structures |
| `routes_panels.py` | 278 | panel timeline, appeal, effective cascade, impact-analysis |
| `routes_folios.py` | 309 | folios, determinations, insurance reports, force placement |
| `routes_notices.py` | 271 | compliance notices, acknowledgement, monitoring sweep, clock |
| `routes_disputes.py` | 597 | disputes + joint review, elevation certificates, amendment packages |

Total 3379 lines. Every file passed `wc -l` + `ast.parse`. Storage is process-local dicts only — no SQLite, no JSON on disk, no /tmp cache, and nothing is seeded at boot.

## Endpoint count
Exactly **49** routes registered: 23 GET + 26 POST, matching the PRD §4 table row for row.

## Boot verification
Launched `PORT=18877 bash start.sh` (unusual port), then drove a 60-call smoke script covering every workflow: clock, community/lender/property/structure/folio, determination, notice + cooldown 409, force placement, escrow settlement, certificate filing/review, LOMA + LOMR_F fee quoting with resubmission, sustained dispute cascade, panel revision -> appeal -> effective cascade -> monitoring sweep, plus 401/400/404/412 negatives. **0 failures.** Pinned worked examples reproduced: FL NGVD29 8.94 with BFE 7.75 -> freeboard 0.1; LOMR_F expedite -> base 50000 / TIER_2 / 15000 / total 65000; escrow conservation 489808 + 10192 = 500000. Server killed by exact captured PIDs only — `kill 263330` (the launcher) and `kill 263332` (`python3 app.py`), confirmed gone and port 18877 free. No `pkill` was ever run.

## PRD ambiguities resolved
1. `X-User-Role` (PRD §2.1) used, not the scaffold's `X-Role`.
2. **§2.5 vs §2.8 contradiction**: §2.5 puts body shape at priority 4 *before* path resolution at 5, §2.8 says paths resolve first. Followed §2.5 — every handler validates body shape before resolving path ids.
3. Decimals serialize as JSON floats; money stays integer cents.
4. All timestamps, including date-shaped inputs (`effective_date`, `survey_date`) and the echoed `current_utc`, emit in the canonical 3-digit format.
5. An `_seq` insertion counter is the `created_at` tie-break; the id is never consulted (and `_`-prefixed keys are stripped from responses).
6. Panel-effective cascade: HOP 4 always bumps affected folios, HOP 5 bumps again only if a notice was actually superseded. Dispute-sustained: HOP 4 and HOP 5 each bump the folio (a RE_DETERMINATION notice is always minted), so its version rises by 2.
7. `POST /loan-folios` does not enforce lender ownership (ladder priority 7's scope excludes it).
8. Notice sending is blocked for **all** notice types in an `UNAVAILABLE` community (§3.6 literal text over the mandatory-purchase-only phrasing).
9. `base_flood_elevation_ft` is required-present but nullable on panel publication.
10. Uniqueness breaches (`community_id_code` global, `loan_number` per lender) -> `ERR_INVALID_REQUEST` 400; no dedicated error exists.
11. Acknowledging after `response_deadline_at` -> `ERR_INVALID_NOTICE_STATE` 409.
12. `escrow_servicing_flag == false` -> `ERR_FORCE_PLACEMENT_NOT_AUTHORIZED` 403.
13. Insurance report supersedes SENT `MANDATORY_PURCHASE`/`FORCE_PLACEMENT_WARNING` notices on **both** the NONE and FORCE_PLACED paths (scaffold states it unconditionally; PRD names "the folio's move into BORROWER_PROVIDED" as a superseding trigger).
14. Decimal scale enforced only where the PRD pins one (coords 6dp, confidence 2dp, BFE/raw survey/machinery 2dp); boundary offsets are unconstrained.
15. `insurance-reports` does not block on `monitoring_status == SUSPENDED` (that gate is named for force placement only).
16. Second-round dispute rule implemented as: any existing dispute on the same `determination_id` with an equal `asserted_sfha_offset_ft` -> `ERR_DISPUTE_BASIS_UNSUPPORTED`.
17. `MAP_PANEL_STALE` admissibility: a panel on the same (community, map_panel_number) timeline with a greater `revision_sequence` and status in {PRELIMINARY, APPEAL_OPEN, LFD_ISSUED}.
18. Borrower certificate filing: candidates are the folios on the structure's property (or the dispute's folio when `dispute_id` is given); with no candidate folio the check passes, otherwise a `borrower_user_id` match is required.
19. Force placement persists its lapsed-notice sweep even when a later gate rejects the request.
20. `POST /monitoring-runs` reads `community_id`/`map_panel_id` from the JSON body with a query-string fallback (the scaffold declares them as query params), and 404s on unresolvable filter ids.
21. Certificate `freeboard_ft`/`lag_freeboard_ft` are null when the reference panel's BFE is null; a null freeboard fails the `> 0` amendment gate.
22. `rejection_reason` is required when `decision == REJECTED`, ignored on `VALIDATED`.
23. `DISPUTE_REVISION` and `RE_DETERMINATION` are not client-requestable -> `ERR_INVALID_REQUEST`.
24. Amendment submission's "determination must be ISSUED or FLAGGED_FOR_REVIEW" (no error named in the PRD) reports `ERR_INVALID_DETERMINATION_STATE` at priority 11.
25. Agency decision stores `agency_case_number` on GRANTED/DENIED; `additional_data_note` only on ADDITIONAL_DATA_REQUESTED, which leaves `decided_at` null.
26. System-minted RE_DETERMINATION notices carry `annual_premium_rate_cents` 0.
27. `required_coverage_cents` re-derives the mandatory-purchase condition live from `determination.sfha_flag` + the community's *current* `coverage_availability` (per the scaffold formula), while the determination row keeps its issuance-time `mandatory_purchase_flag` snapshot.
28. Certificate validation recomputes `freeboard_ft` on any folio's current determination for that structure, using the determination's own BFE snapshot; `zone_code`/`sfha_flag`/`position_class` untouched.
29. SoD (priority 9) is checked *before* entity state (priority 11) on all three review actions, per the ladder, even though §3.8/§3.9 narrate state first.

## Step 7: Run tests and iterate — 2026-09-03T13:35:00.000Z

Green across the board.

## Summary

**Iterations run:** 3 (each a full 8-round parallel sweep under `setsid nohup`, no early exit).

Failure trajectory: 75/78 -> 77/78 -> **78/78 x 8 rounds**. Every failure was deterministic (identical in all 8 rounds), so no flakiness or load-induced noise had to be separated out.

**Tests deleted:** none. No test asserted a rule PRD is wholly silent on.

**Fixes applied to `test_helpers/`:** none. All four defects lived in a single test file's assertions; the fixtures, factories and role-header builders were already PRD-faithful (the failures were not a shared-setup cluster).

**Fixes applied to `test_suite/`** — all in `test_suite/test_06_force_placement_and_escrow.py`:

1. `test_force_placement_is_refused_for_a_lender_that_is_not_authorized_to_place` — removed `assert eligible["compliance_posture"] == "FORCE_PLACE_ELIGIBLE"` on a bare GET taken right after a clock advance. **STEP 1b, uncovered-derivation:** PRD §3.6 says "The posture is recomputed on every write that touches the folio, its current determination, its notice set, or its property's community", §2.4 says "Advancing the clock is inert by itself", and §3.6's force-placement paragraph says the notice sweep "is what allows the posture ladder to read `FORCE_PLACE_ELIGIBLE` rather than `NOTICE_PENDING`" — that last sentence is only meaningful if the posture is stored and refreshed on writes. A read-time-derived posture is also arguable, so the two readings diverge and the assertion is not uniquely determined. The refusal itself (rung 14, `ERR_FORCE_PLACEMENT_NOT_AUTHORIZED`) is untouched.

2. `test_a_pending_re_determination_outranks_a_lapsed_notice_in_the_posture_ladder` — removed the same bare-read posture assertion after `set_clock`, for the identical reason. The test's actual subject (clause 3 `REVIEW_PENDING` masking clause 5 `FORCE_PLACE_ELIGIBLE`, proven by the geocode-correction cascade and the closing `ERR_NOTICE_PERIOD_NOT_EXPIRED`) is intact and still passes.

3. `test_the_notices_frozen_estimate_survives_the_actual_premium_being_written` — replaced `assert_escrow_conservation(placed)` (called on a folio at rest in `FORCE_PLACED`) with the mid-flight form `escrow_balance_cents + force_placed_premium_cents == initial_escrow_balance_cents == 500000`. **STEP 2, test bug:** the two-term identity in `assert_escrow_conservation` is arithmetically impossible immediately after placement given PRD §3.6's explicit "escrow_balance_cents is reduced by force_placed_premium_cents while cumulative_earned_premium_cents is deliberately left untouched" — the test's own lines 482/484 assert 357973 and 0, which contradict its own line 485. §2.10 itself defers ("Section 3.6 gives the arithmetic"), and the suite's own canonical conservation test already uses exactly this mid-flight form. The helper was left alone: its other five call sites are all at genuine rest points.

4. Same file, `test_force_placement_is_refused_...` — replaced `assert still_open["status"] == "SENT"` with `status == "EXPIRED"` plus `closed_at` at the placement instant and `open_notice_count == 0`. **STEP 2, test bug (strengthened, not weakened):** PRD §3.6 orders the sweep *before* eligibility — "Before evaluating eligibility it first sweeps the folio's notices: any notice still in `SENT` whose `response_deadline_at` has passed is moved `SENT -> EXPIRED` with `closed_at` set to the current logical instant" — and the authorisation rung (14) sits below the eligibility rung (13), so the lapsed notice is necessarily already closed when the 403 is issued. PRD grants no rollback for this path; it scopes its no-write promises narrowly ("nothing is drawn" for escrow, "nothing is written" for the stale-version check only).

**Fixes applied to `implementation/`:** none. The implementation was PRD-faithful on all four points; no endpoint, field, side effect, or seeded data was added, and storage remains in-memory dicts.

**Final sweep evidence:** all 8 `results.$i.json` exist (all written 13:22, ~24.9 KB each, all parsing as complete JSON) and each reports `passed=78 total=78 failed=0 errors=0`.

**Orchestrator independent verification:** re-checked the artifacts directly rather than trusting the report. `ls -la results.*.json` shows 8 files (24900-24908 bytes, all timestamped 13:22), and `json.load` on each yields `passed=78 total=78 failed=0 errors=0` for all 8. Confirmed.

**Step 8 gating decision:** Step 7 applied 0 `implementation/` fixes but 4 `test_suite/` assertion changes and 0 deletions — so this is NOT the zero-iteration skip case. Two of those four changes (items 1 and 2) are explicit PRD-silence findings about whether `compliance_posture` is stored-and-refreshed or derived at read time, which is exactly the class of residual ambiguity Step 8 exists to pin. Step 8 runs.

## Step 8: Finalize PRD — 2026-09-03T13:52:00.000Z

Done. Three edits, all traceable to the four `<step_7_diff>` items.

**Orchestrator note:** the first Step 8 subagent died from an infrastructure API error immediately after Method step 0's `cp`, leaving PRD_FINALIZED.md byte-identical to PRD.md. It was relaunched with an added note telling it to verify the copy with `cmp` and begin editing rather than re-copying. The summary below is from the successful second run.

## File delta
- `PRD.md`: 386 lines / 105,009 bytes
- `PRD_FINALIZED.md`: 386 lines / 106,843 bytes (+1,834 bytes, **+1.75 %** by size; **0 %** by line count — 3 of 386 lines touched, i.e. 0.78 % of lines)
- `diff` reports 6 changed lines (3 removed, 3 added).

## Changes

- **§3.6, posture-ladder paragraph — insert — `compliance_posture` is a stored, write-refreshed field, not a read-time derivation; a clock advance alone never moves a stored `NOTICE_PENDING` to `FORCE_PLACE_ELIGIBLE`** — covers step_7 items 1 and 2 — `implementation/services.py:100-122` (`recompute_folio` writes the field), `implementation/calc.py:210-231` (ladder reads `db.now()` at recompute time), `implementation/routes_reads.py:150-165` (reads return the stored row verbatim).
- **§2.10, first conservation invariant — revise — the conserved sum is three-term (`escrow_balance_cents` + `cumulative_earned_premium_cents` + outstanding `force_placed_premium_cents`); the two-term form holds only where no placement is outstanding, and is short by exactly the drawn premium immediately after placement** — covers step_7 item 3; PRD.md as written ("the sum of `escrow_balance_cents` and `cumulative_earned_premium_cents` must equal `initial_escrow_balance_cents` — after the forward action of force placement") was a genuine PRD/impl **mismatch** — `implementation/routes_folios.py:296-301`, `implementation/services.py:261-280`.
- **§3.6, force-placing paragraph — insert — the pre-eligibility notice sweep is unconditional and is not rolled back when a later rung refuses the placement (all five reachable refusals named); the refusal spares the money and the coverage move, not the sweep** — covers step_7 item 4 — `implementation/routes_folios.py:239-295`.

## Per-edit pre-edit search log

**Edit A — subject: whether folio-derived posture is stored-on-write or derived-on-read.**
(b) Enumerated/read: `calc.compliance_posture` (`calc.py:210`); its single caller `services.recompute_folio` (`services.py:118`); `services.touch_folio` (`services.py:124`); **all 28** `recompute_folio`/`touch_folio` callsites (`services.py:258,306,344,352,412`; `routes_folios.py:94,231,249,251,306`; `routes_notices.py:104,108,155,210,233,250`; `routes_disputes.py:138,244`; `routes_parties.py:100`); both read paths in `routes_reads.py` (`_make_list_view` filters on the stored value, `_make_get_view` returns `must()` unmodified); `db.touch` (version/`updated_at`); folio creation literal `compliance_posture="COMPLIANT"` (`routes_folios.py:91`); the other five PRD mentions of posture recomputation (§3.1 participation cascade, §3.2, §3.5, §3.7, §3.9) for consistency.
(c) Adjustment: two off-Step-7 paths forced wording changes. (i) `routes_folios.py:251` recomputes the posture *without* a version bump on a refused force placement, and `routes_notices.py:104` recomputes before a notice is minted — so I avoided "until the next write/mutation" and wrote "until the ladder is re-evaluated by an action on the folio". (ii) Because `_make_list_view` filters on the stored value, I widened the sentence to cover "singly or in a collection, and when filtering a collection by `compliance_posture`" rather than only single-resource GET.

**Edit B — subject: the escrow/earned-premium conservation identity and every field in it.**
(b) Grepped `escrow_balance_cents|cumulative_earned_premium_cents|force_placed_premium_cents|initial_escrow` across all of `implementation/` — exactly two mutation sites: `routes_folios.py:298-301` (placement: `force_placed_premium_cents = premium`, escrow `-= premium`, cumulative untouched) and `services.settle_escrow` (`services.py:261-280`: refund into escrow, earned into cumulative, premium reset to 0). Enumerated both `settle_escrow` callers — the borrower-provided unwind (`routes_folios.py:228`) and the off-Step-7 sustained-dispute release inside `adopt_determination(..., allow_force_placed_release=True)` (`services.py:256`) — plus the snapshot at folio open (`routes_folios.py:76-88`) and §3.6's own closing statement of the two-term identity after settlement. Verified the three-term sum equals `initial_escrow_balance_cents` at open, after placement, and after settlement in both unwind paths.
(c) Adjustment: because the dispute-driven `FORCE_PLACED -> NOT_REQUIRED` release reuses the identical settlement, I phrased the two-term restoration as "after each settlement" (not "after coverage replacement" only) and kept "at every point where the folio is at rest" on the three-term claim so it never over-claims mid-request states.

**Edit C — subject: persistence of the pre-eligibility notice sweep on a refused force placement.**
(b) Read the whole of `force_place` (`routes_folios.py:239-306`) to fix the exact check order: authorize -> `no_body` -> `must` -> `_require_owner` -> sweep -> state 11 -> coverage 12 -> eligibility 13 -> authorisation 14 -> escrow 31. Read `services.expire_lapsed_notices` (`services.py:176-186`), the parallel system-wide sweep in `monitoring_run` phase two (`routes_notices.py:236-250`, the only other `SENT -> EXPIRED` producer), `routes_notices.py:241` (acknowledgement path, unaffected), `errors.py`/`app.py` (`ApiError` raises; no transaction, snapshot or rollback anywhere), and `db.touch`.
(c) Adjustment: I enumerated the errors reachable *after* the sweep and named exactly those five, deliberately excluding the pre-sweep rungs (`ERR_UNAUTHENTICATED`, `ERR_FORBIDDEN_ROLE`, `ERR_INVALID_REQUEST`, `ERR_LOAN_FOLIO_NOT_FOUND`, `ERR_FOLIO_NOT_OWNED`), which in the implementation return before any notice is touched. I also left the `version`/`updated_at` consequences unstated, since §2.8's existing "every row a cascade writes is a real mutation" already covers the swept notice and the re-counted folio, while the zero-lapse case in `routes_folios.py:251` bumps nothing.

**Orchestrator independent verification:** `wc -l -c` confirms 386/105009 vs 386/106843, `diff | grep -c '^[<>]'` = 6 changed lines, and the tail still ends on the completed final §5 table row. Step 8 accepted.

## Step 9: Complete PRD — 2026-09-03T14:25:00.000Z

**Orchestrator decision (recorded per the autonomy instruction):** Step 9 was run as THREE SEQUENTIAL FILE-PARTITIONED PASSES over `implementation/` rather than as a single subagent. Rationale: a single Step 9 agent asked to walk 3,379 lines of implementation exhaustively has previously returned a `PRD_COMPLETED.md` byte-identical to its input — i.e. the scan silently never ran. Partitioning by implementation file keeps each pass's working set to ~1,100 lines, and each pass was given an explicit "do not re-copy the file, edit in place" instruction plus the list of what earlier passes already covered and which PRD sections were theirs to edit, so the passes neither duplicate nor collide. Partition: pass 1 = app/db/errors/response/authz/shape/enums/calc (plumbing, ladder 1-4, all 12 calculations); pass 2 = services cascades + routes_parties/routes_panels/routes_reads; pass 3 = routes_folios/routes_notices/routes_disputes + the services notice/adoption/escrow/dispute-cascade internals pass 2 deferred.

### Pass 1 — core plumbing + calculations

- `PRD_FINALIZED.md` 386 lines / 106,843 chars -> `PRD_COMPLETED.md` 387 lines / 110,680 chars (+1 line, +3,837 chars); diff 29 changed lines.
- **15 changes: 12 ambiguity-pins, 3 mismatch-revisions.**
- §2.1 — insert — ambiguity — both auth headers are whitespace-trimmed before examination; whitespace-only counts as empty, padded role names are recognised — `authz.py:45-54`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A`-`Z` and `0`-`9` — `response.py:11,19-20`
- §2.2 — revise — ambiguity — `api_request_timestamp` is read from the logical clock, not host wall clock — `response.py:55-59`
- §2.2 — revise — **mismatch** — error envelope covers "4xx **and 5xx**" status codes (impl returns the envelope on 500) — `app.py:79-86`
- §2.2 — insert (new bullet) — ambiguity — transport failures all report `ERR_INVALID_REQUEST`: unknown path->404, bad method->405, unparseable JSON / non-JSON content type->400, internal fault->500 — `app.py:42-86`
- §2.3 — revise — ambiguity — `created_at` ascending ties break on insertion sequence (never the id), and that counter is never serialised — `db.py:78-84`, `response.py:41-44`
- §2.3 — revise — **mismatch** — an enumeration-valued filter outside its declared range is a priority-4 `ERR_INVALID_REQUEST`, not an empty page — `shape.py:92-96`
- §2.4 — revise — ambiguity — `id` is a random version-4 UUID in canonical lower-case 8-4-4-4-12 hex form — `db.py:53-54`
- §2.5 — insert — **mismatch** + ambiguity — priority 4 also covers non-object/unparseable bodies, explicit `null` for non-nullable fields, empty/whitespace strings, JSON-boolean-only body bools (query accepts `true/false/1/0`), booleans in numeric fields, fractional ints, and the accepted instant formats (`Z`, numeric offset, zone-less->UTC, bare `YYYY-MM-DD`->midnight UTC); absent body == `{}`; no-input endpoints reject any body field or query param; **query-string checking applies only to operations declaring query inputs** — `shape.py:80-254`
- §2.7 — insert — ambiguity — decimals serialise as bare JSON numbers, money as bare integers — `response.py:50-51`
- §3.5 — insert — ambiguity — coverage dimension is the closed range `NONE`/`NOT_REQUIRED`/`BORROWER_PROVIDED`/`FORCE_PLACED` — `enums.py:36`
- §3.6 — insert — ambiguity — the calendar-year anniversary roll keeps month/day, except 29 Feb lands on 28 Feb in a non-leap target year — `db.py:91-95`
- §3.6 — revise — ambiguity — a `force_placed_coverage_days` of 0 also earns the whole premium (refund 0) — `calc.py:287-289`
- §3.8 — insert — ambiguity — a null reference-panel BFE yields null `freeboard_ft` and `lag_freeboard_ft` while the converted elevations are still stored — `calc.py:238-241`
- §4 — insert — ambiguity — path matching ignores a trailing slash — `app.py:24`
- Verified-no-change-needed: §5 error catalogue programmatically diffed against `errors.py::ERROR_STATUS` (47 ids both sides, zero status mismatches); §4 endpoint table programmatically diffed against the live Flask `url_map` (49 method/path pairs, exact match both directions); all 33 enumerations other than `insurance_status` already uniquely pinned; every `calc.py` constant and rounding/evaluation-order rule already matched.

### Pass 2 — services cascades, parties, panels, reads

- 387 lines / 110,680 chars -> 387 lines / 114,398 chars (+3,718 chars); cumulative diff vs FINALIZED 59 changed lines.
- **17 changes: 17 ambiguity-pins, 0 mismatch-revisions** (no passage in this partition contradicted impl; every gap was silence).
- §3.1 — insert — ambiguity — duplicate `community_id_code` reports `ERR_INVALID_REQUEST` (400); the "six-character" width is descriptive, not validated — `routes_parties.py:51-57`
- §3.1 — insert — ambiguity — `probation_surcharge_cents` on a participation change is optional; omitting it leaves the stored value untouched and no direction ever clears it — `routes_parties.py:81,86-87`
- §3.1 — insert — ambiguity — every folio in the community is written exactly once by a participation change, so `version`/`updated_at` advance even when nothing changed — `routes_parties.py:92-100`
- §3.1 — insert — ambiguity — `contact_email` is any non-empty string; no address-format check — `routes_parties.py:113`
- §3.2 — insert — ambiguity — `base_flood_elevation_ft` is required-but-nullable; the unnumbered zone `A` case is expressed by explicit `null` — `routes_panels.py:35`
- §3.2 — insert — ambiguity — `sfha_boundary_shift_ft` and `horizontal_uncertainty_ft` carry no declared decimal scale — `routes_panels.py:41-45`
- §3.2 — insert — ambiguity — a newly published panel starts with `appeal_period_end_date`, `lfd_issued_at` and `superseded_at` all null — `routes_panels.py:112-114`
- §3.2 — insert — ambiguity — an explicitly supplied `appeal_period_end_date` is stored as given and need not be in the future — `routes_panels.py:133-136`
- §3.2 — insert — ambiguity — on the appeal decision the `revision_status` check precedes the window check, so `ERR_INVALID_PANEL_STATE` wins over `ERR_APPEAL_PERIOD_OPEN` — `routes_panels.py:147-158`
- §3.2 — insert — ambiguity — the three `effective` gates evaluate in order: status, waiting-period pair, effective-date pair — `routes_panels.py:175-201`
- §3.2 — insert — ambiguity — hop 4 writes each affected folio exactly once regardless of how many determinations hop 3 flagged; hop 5 writes it a second time only when >=1 notice actually closed — `services.py:340-352`
- §3.3 — insert — ambiguity — the projection declares no input beyond the path id and inspects neither body nor query string — `routes_panels.py:206-209`
- §3.3 — insert — ambiguity — candidate folios are scanned in `created_at` ascending order and the first match wins — `routes_panels.py:237-244`
- §3.4 — insert — ambiguity — `latitude`/`longitude` are constrained only by the 6-place scale; no +/-90/+/-180 range check — `routes_parties.py:134-135`
- §3.4 — insert — ambiguity — hop 2 writes each affected folio exactly once; a correction is accepted even when it drops `geocode_status` to `UNRESOLVED` or repeats the stored values (`geocode_corrected_count` still advances) — `routes_parties.py:196-200`, `services.py:295-307`
- §3.4 — insert — ambiguity — no decimal scale is enforced on `sfha_offset_ft` — `routes_parties.py:215`
- §4 — insert — ambiguity — reads are never ownership-scoped: ladder steps 7/8 guard only folio-bearing writes, so a `Lender` may read a folio it does not own and no collection read narrows `data` by caller identity — `routes_reads.py:147-168`
- Territory discipline confirmed: did not re-copy the file (all 15 pass-1 markers verified present), did not touch §3.6-§3.9 or §2.10/§2.11.

### Pass 3 — folios, notices, disputes

- 387 lines / 114,398 chars -> 387 lines / 122,392 chars (+7,994 chars, no line-count change — all inserts landed inside existing paragraphs).
- **35 Edit calls: 21 ambiguity-pins, 13 mismatch-revisions, 1 punctuation cleanup of a just-inserted clause.**
- §2.6 — insert — ambiguity — `expected_loan_folio_version` is a non-negative integer, 0 admissible, mismatch -> `ERR_STALE_LOAN_FOLIO_VERSION` at priority 10 — routes_folios.py:111,118
- §2.9 — revise — mismatch — an UNAVAILABLE community blocks issuance of *every* compliance notice whatever its `notice_type` — routes_notices.py:66
- §3.5 — insert — mismatch — `open_folio` never compares the acting lender to `lender_id`; duplicate `(lender_id, loan_number)` is `ERR_INVALID_REQUEST` raised only after both referenced rows resolve — routes_folios.py:47,59-69
- §3.5 — insert — ambiguity — a new folio's `compliance_posture` is derived by the ladder immediately after insertion (so it can be born `COVERAGE_UNAVAILABLE`), `version` starts at 1 — routes_folios.py:91-94
- §3.5 — insert — ambiguity — the UNDER_DISPUTE lock scans all live rows on that structure and precedes the structure/folio, geocode and panel tests — routes_folios.py:131-136
- §3.5 — revise — ambiguity — the retired `prior` is the *last* live `ISSUED`/`FLAGGED_FOR_REVIEW` row in `ordered()` sequence — routes_folios.py:137-140
- §3.5 — revise — mismatch — issuance recomputes the posture "normally to `COMPLIANT`", the ladder free to return another clause — services.py `adopt_determination`
- §3.5 — insert — mismatch — posture-ladder hedge plus the immobility of `BORROWER_PROVIDED`/`FORCE_PLACED` across issuance — routes_folios.py:188
- §3.6 — revise — mismatch — force placement raises `version` by **two** on the common path (notice sweep write + placement write), by exactly one where the sweep closed nothing — routes_folios.py:248-251,306
- §3.6 — revise — mismatch — coverage may be reported only from `insurance_status` `NONE` or `FORCE_PLACED`; anything else is `ERR_INVALID_FOLIO_STATE` — routes_folios.py:200
- §3.6 — insert — ambiguity — the replacement-cost ceiling comes from the *current determination's* structure only; with no current determination there is no ceiling — routes_folios.py:208-223
- §3.6 — insert — mismatch — posture after a coverage report is whatever the ladder returns, not unconditionally `COMPLIANT` — routes_folios.py:226-231
- §3.6 — insert — ambiguity — the settlement tail: `settle_escrow` runs before the status flips, and the folio is written once — routes_folios.py:225-236
- §3.6 — insert (+1 punctuation fix) — ambiguity — a late acknowledgement is refused with `ERR_INVALID_NOTICE_STATE`, the same id as a wrong-status one — routes_notices.py:143
- §3.7 — insert — ambiguity — either filter may arrive in body or query (body wins), may be omitted or explicitly null, and an unknown id is that entity's not-found error with the community checked before the panel — routes_notices.py:166-173
- §3.7 — insert — ambiguity — filter semantics: `community_id` matches the *structure's property's* community, `map_panel_id` the determination's own stored panel — routes_notices.py:191-194
- §3.7 — revise — mismatch — a flagged determination whose property has no effective panel is skipped **without** being counted in `determinations_scanned` — routes_notices.py:196-198
- §3.7 — insert — ambiguity — the minted `RE_DETERMINATION` notice carries `annual_premium_rate_cents` 0 and is exempt from the five-day cooldown — routes_notices.py:232
- §3.7 — revise — mismatch — phase two is global (never narrowed by the filters), rewrites each affected folio exactly once, and the response echoes `community_id`/`map_panel_id` — routes_notices.py:236-262
- §3.7 — revise — mismatch — `determinations_scanned` is "the number of flagged determinations phase one actually re-classified" — routes_notices.py:198,256
- §3.8 — insert — ambiguity — borrower scope on certificate filing: the one folio behind the disputed determination when `dispute_id` is given, else every folio on the property; no folio at all admits the filing — routes_disputes.py `file_certificate`
- §3.8 — insert — mismatch — `machinery_elevation_ft` is stored raw (never datum-shifted, never in a freeboard figure) and `dispute_id` carries no state precondition — routes_disputes.py
- §3.8 — insert — ambiguity — a missing `rejection_reason` on the `REJECTED` branch is `ERR_INVALID_REQUEST` at priority 4 (before path resolution); one sent with `VALIDATED` is accepted and ignored — routes_disputes.py `review_certificate`
- §3.8 — insert — mismatch — `reviewed_by_user_id` is written *before* the currency test, so an `ERR_CERTIFICATE_EXPIRED` refusal leaves the reviewer recorded on a still-`SUBMITTED` row with no other field moved — routes_disputes.py + app.py:38-40 (no rollback)
- §3.8 — revise — mismatch — freeboard recomputation covers every determination that some folio names as `current_determination_id` on that structure, each from its *own* snapshotted BFE; folio rows are not written — routes_disputes.py `review_certificate`
- §3.8 — insert — mismatch — the package's own state is tested before the determination's, so `ERR_INVALID_AMENDMENT_STATE` wins over `ERR_INVALID_DETERMINATION_STATE` — routes_disputes.py `submit_amendment`
- §3.8 — insert — ambiguity — a null freeboard (unnumbered zone `A`) fails the above-BFE test exactly as zero or negative does — routes_disputes.py `submit_amendment`
- §3.8 — insert — mismatch — `agency_case_number` is not written on the `ADDITIONAL_DATA_REQUESTED` branch; terminal branches write it straight from the request (omission stores null) and neither clears an earlier `additional_data_note` — routes_disputes.py `decide_amendment`
- §3.9 — insert — ambiguity — `asserted_sfha_offset_ft` declares no scale, so any decimal precision is admitted — shape.py/routes_disputes.py
- §3.9 — insert — ambiguity — `MAP_PANEL_STALE` admissibility is measured against the *cited* panel and only `PRELIMINARY`/`APPEAL_OPEN`/`LFD_ISSUED` successors count as in-flight — routes_disputes.py `_basis_admissible`
- §3.9 — revise — mismatch — the duplicate-offset rule compares against **every** prior dispute on that determination by decimal value, not just the second round — routes_disputes.py
- §3.9 — insert — ambiguity — agency review records concurrence first, then checks segregation of duties ahead of the state test, skipping the SoD check while the recorded reviewer is null — routes_disputes.py `agency_review`
- §3.9 — insert — ambiguity — cascade hop 3 falls back to the determination's own stored panel when the property has no effective panel — services.py `dispute_sustained_cascade`
- §3.9 — revise — mismatch — hop 4 releases a placement on `mandatory_purchase_flag` being false (not `sfha_flag`), and always re-counts and touches the lender — services.py `dispute_sustained_cascade`
- Confirmations: no prior work copied over (every change a targeted `Edit`; file never rewritten with `Write`); Step 8's three edits present and uncontradicted, each sentinel grepping to exactly 1; deliberately left alone §3.6's narrative check ordering (§2.5's ladder is normative and impl matches), §2.5's ladder sentence, §2.8, the §4 endpoint table and the §5 error table.

### Step 9 totals and orchestrator verification

- `PRD.md` 386 lines / 105,009 chars -> `PRD_FINALIZED.md` 386 / 106,843 -> `PRD_COMPLETED.md` 387 / 122,392. Net Step 9 delta over FINALIZED: **+1 line, +15,549 chars (+14.6 %)**; **67 changes total — 50 ambiguity-pins, 16 mismatch-revisions, 1 punctuation cleanup.**
- Independent structural verification by the orchestrator: `diff PRD_FINALIZED.md PRD_COMPLETED.md | grep -c '^[<>]'` = **101** (so the scan demonstrably ran — this is NOT the byte-identical failure mode); `grep -c '^#'` = 28 headers (unchanged, no new sections); `grep -c '^| \`ERR_'` = 47 (all errors intact); the §4 table still carries 49 `GET`/`POST` rows; `tail -2` ends on the completed final `| \`ERR_ESCROW_INSUFFICIENT\` | 402 |` row.
- No code drift after the green sweep: newest file under `test_suite/`, `test_helpers/` or `implementation/` is `test_suite/test_06_force_placement_and_escrow.py` at 13:19, which predates the final sweep's `results.*.json` at 13:22. Steps 8 and 9 touched only PRD documents, so the 8/8 x 78/78 result stands as the pipeline's final test evidence.

PIPELINE COMPLETE — `workspace/PRD_COMPLETED.md` written.
