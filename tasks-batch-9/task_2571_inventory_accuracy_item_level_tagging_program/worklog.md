# Worklog — task_2571_inventory_accuracy_item_level_tagging_program

## Step 1: Create task directory — 2026-09-03T13:01:55.302Z

Created pre-assigned directory `/home/ubuntu/github/CodingPRD/tasks/task_2571_inventory_accuracy_item_level_tagging_program` and its `workspace/` subdirectory. Index 2571 was fixed by the scenario number (no auto-allocation scan performed, per orchestration instructions, because up to 32 pipelines run concurrently on this host).

## Step 2: Generate Scaffold — 2026-09-03T14:57:00.000Z

All three scaffold artifacts for task 2571 are complete and lint-clean.

**Files** (`/home/ubuntu/github/CodingPRD/tasks/task_2571_inventory_accuracy_item_level_tagging_program/`)
- `SCAFFOLD.yaml` — 3862 lines, §1.0–§1.7 only (no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2105 lines, single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4778 lines, single key `scaffold_corner_design`

**§1.0–§1.7 counts:** 15 entities, 7 state machines, 3 §1.2.1 OCC rules, 13 global constants, 13 calculations, 52 ordered validations, 81 endpoints, 69 errors, 7 roles. Domain `inventory-accuracy-tagging-program`, prefix `/inventory-integrity`; profile: primary `ledger_reconciliation` + `compliance_audit`, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers]`, flat/cyclic, `segregation_of_duties`, `immediate`.

**§1.8:** 9 rules / 23 instances (dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 2, resource_temporal_overlap 3, compensating_invariant 3).

**§1.9:** 9 sections / 111 instances — entities 15, state_machines 18, calculations 12, validations 10, endpoints 9, errors 25, rbac 10, cross_cutting_complexity_layers 10, consistency_model 2. 77 carry full `test_recipe`s (884 structured calls across §1.8+§1.9); 34 are `excluded_because` stubs, every cited `difficulty_instance` verified to exist by name, none carrying a forbidden `test_recipe`. All 133 instance names unique across the two design files, and all 69 error ids are reachable from §1.8 ∪ §1.9.

**Lint:** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`

**Design adjudications made while replaying chains**
- Fixed two SCAFFOLD self-inconsistencies rather than bending the tests: the VarianceInvestigation `CAUSE_APPROVED→CLOSED` actor now matches the endpoint's `roles` (InventorySupervisor), and the count-reconcile side-effect prose now agrees with `physical_reconciliation`'s remainder-to-`unresolved_cents` rule (it previously said "remainder to theft").
- Priority 64 (`ERR_NO_COVERING_SHRINK_PERIOD`) applies to `/submit` unconditionally, so three §1.9 calculation fixtures were repaired by adding a covering ShrinkPeriod instead of weakening the validation.
- Corrected my own fixture drift: CounterFirm payloads now use the declared `certification_level` / `max_lines_per_pass` inputs, and an assert that used a non-existent `physical_inventory_id` filter on `/adjustments` was switched to `?posting_state=POSTED`.
- Error coverage strategy: real recipes only for ids nothing else reaches (auth, per-family 404s and duplicates, tag scheme/sample, no-covering-period, period overlap/inverted range, no-vendor-shortage, tag-hold vs approval-required precedence, duplicate count line, open investigations, recount required, investigation invalid state); ids whose sharpest form lives in §1.8 are stubs. Negative-path instance names deliberately match the lint's negative-name pattern so intentional role/payload violations are not miscounted.
- Every numeric assert is pre-computed as a literal (e.g. `floor(10000*12340/123400)=1000`, read-rate 9600 vs `MIN_READ_RATE_BPS` 9800, vendor score band flip at exactly 9100 ≥ 9000, threshold 10000 vs value_impact 24680).

## Step 3: Copy Shared Files — 2026-09-03T14:58:26.766Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T15:14:30.000Z

PRD generation complete.

**Output:** `workspace/PRD.md` — **567 lines**, ending at a genuine boundary (last row of the §5 error table, no audit footer).

**Sections emitted**
- §1 Introduction
- §2 Global Specifications: 2.1 RBAC (7 roles, identity scoping, segregation of duties) · 2.2 Response Structure (verbatim from the skill file) · 2.3 Pagination · 2.4 Common Properties & Logical Clock · 2.5 Stale-Read Protection (3 OCC paths) · 2.6 Units/Money/Rounding · 2.7 Derivation Order & Cascades · 2.8 Path Resolution & Discovery · 2.9 Order of Rejection (13-step ladder) · 2.10 Conserved Quantities
- §3 Business Logic, 10 subsections: 3.1 merchandise frame · 3.2 stock positions & promising gate · 3.3 source tagging & read-quality verification · 3.4 scheduling, coverage & window geometry · 3.5 count submission · 3.6 variance investigation · 3.7 adjustments, authority ladder & integrity scan · 3.8 shrink periods & vendor chargebacks · 3.9 physical inventory & reconciliation waterfall · 3.10 store fulfillment posture
- §4 API Endpoint Specifications (81-row table, generated from the scaffold) · §5 Error Code Reference (69-row table)

**Coverage (verified mechanically against SCAFFOLD.yaml)**
- Endpoints: **81/81** paths present.
- Errors: **69/69** present, and every one appears at least twice — i.e. in prose as well as in the §5 table.
- Validations: **52/52** — each validation's error id and its check condition are stated in prose (auth/existence ladder in §2.9 and §2.8; business rules in their §3 sections).
- Calculations: **13/13** stated in full prose with their pinned worked examples and forbidden alternatives.
- State machines: **7/7**; every `from`/`to` state of every transition appears in backticks, including the parallel `approval_state` × `posting_state` machine and all cyclic edges.
- Contract 1 (field-name coverage): 132 entity fields, 77 endpoint inputs, 50 computed-read output keys, 15 path params — **0 missing** after a repair pass that added `count_task_id` and `physical_inventory_id` (previously only present inside path templates).
- Contract 3 (§3 path purity): scripted scan of all 232 §3 lines — **0** backtick tokens starting with `/`, bare HTTP methods, or method+path combinations.
- Hygiene: no fuzzy quantifiers, no pseudocode operators (`==`, `>=`, `+=`, `floor(`, `min(`, `AND`/`OR`) anywhere in the document; no scaffold-internal vocabulary (`calculations.*`, `state_machines.*`, `§1.x`, or raw constant names like `PHYSICAL_BLACKOUT_BUFFER_DAYS`) leaked — four §4 table descriptions were rewritten to remove `calculations.*` references.

**Zero-Silence decisions**
1. **TagBatch scrap vs. tag-integrity hold (scaffold contradiction).** The `VERIFICATION_FAILED → SCRAPPED` transition and the `StockPosition.tag_integrity_hold` field description both say the hold is cleared *only* by a `VERIFIED_PASS` batch, while the `/scrap` endpoint's `side_effects` say scrapping clears it. I followed the two-source majority: **scrapping does not clear the hold**, stated explicitly in §3.3.
2. **Count-task reconcile roles.** The `COUNTED → RECONCILED` transition names `InventoryAnalyst` as actor, but the endpoint's `roles` and the role model both give `InventorySupervisor` and `ShrinkController`. I used the endpoint roles (consistent in two of three sources) in both §3.5 and the §4 table.
3. **§4 descriptions truncated to the first sentence** of each scaffold description, deliberately dropping trailing clauses that referenced internal constant names; the full rules those clauses summarised are carried in §3.

**Orchestrator truncation check (per launch instructions):** independently ran `wc -l` (567) and `tail -15`; the file ends with the `ERR_CREDIT_EXCEEDS_BALANCE` row of the §5 table — a real section boundary, not mid-sentence. No regeneration needed.

## Step 6: Generate Implementation — 2026-09-03T15:57:00.000Z

The implementation is complete, boots cleanly, and was smoke-tested end to end.

## Files written (all in `workspace/implementation/`)

| file | lines | role |
|---|---|---|
| `start.sh` | 10 | reads `$PORT` (default 10000), guarded `pip install`, `exec python3 app.py` in the foreground |
| `requirements.txt` | 1 | `flask==3.0.3` |
| `app.py` | 70 | blueprint registration, `ApiError`/404/405/catch-all handlers, `app.run(host="0.0.0.0", port=$PORT)` |
| `db.py` | 117 | 15 in-memory dicts + logical clock (`2026-08-01T00:00:00Z`), `_seq` counter, no seeding |
| `errors.py` | 102 | all 69 error ids with HTTP statuses, grouped by rejection tier |
| `response.py` | 107 | envelope (`meta`/`response_type`/`data`), `req_`+20 id, 3-digit timestamps, pagination |
| `middleware.py` | 88 | 7 roles, RBAC, identity scope (Store/Vendor/CounterFirm), segregation of duties |
| `validate.py` | 247 | two-pass body validation (all `ERR_INVALID_REQUEST` before all `ERR_INVALID_ENUM_VALUE`), 15 not-found maps, query filters |
| `calc.py` | 671 | all 13 calculations + derivation cascade (position → store posture → one-way schedule acceleration) |
| `routes_reference.py` | 317 | categories, stores, vendors, counter firms, items, fulfillment-eligibility, `/_clock/set_current_utc` |
| `routes_positions.py` | 325 | stock positions, `/accuracy`, `/integrity-scan`, adjustment request/approve/reject/post/reverse |
| `routes_tags.py` | 220 | tag batches: encode/receive/verify/rework/scrap |
| `routes_counts.py` | 497 | schedules, tasks, lines, submit/return-to-count/reconcile/void |
| `routes_investigations.py` | 163 | assign/propose/return/approve-cause/close + reads |
| `routes_shrink.py` | 287 | periods, dual-variant `/attribution`, provisional/reopen/final close, chargebacks, credits |
| `routes_physical.py` | 360 | schedule/start/lines/complete-pass/order-recount/reconcile/certify/abandon + line reads |

## Coverage

- **Endpoints: 81 / 81** — verified by enumerating `app.url_map` (exactly 81 method+rule pairs, no extras, no duplicates).
- **Calculations: 13 / 13** — `count_variance_valuation`, `stock_accuracy_pct`, `shrink_attribution` (both variants), `adjustment_authority_threshold`, `vendor_shortage_chargeback`, `tag_verification_outcome`, `count_coverage_pct`, `position_promising_state`, `store_fulfillment_posture`, `integrity_scan_corrections`, `physical_reconciliation`, `physical_inventory_blackout_interval`, `count_task_window_overlap`.
- **Validations: 52 / 52** — the 52 ordered rules resolve to 49 distinct error ids, every one of which is raised somewhere in the code (statically checked).
- **Error ids: 69 / 69 reachable** — declared set in `errors.py` and the set referenced by the route/calc modules are identical (no unreferenced, no undeclared).

## Boot / smoke result

Booted on a random high port via `bash start.sh` (foreground, 0.0.0.0). `GET /inventory-integrity/categories` → **200**; `POST /inventory-integrity/vendors` → **201**. Three scripted smoke passes exercised ~70 of the 81 endpoints and reproduced the PRD's pinned numbers exactly:

- physical inventory pass: book 183400, counted 156060, net −27340, `net_variance_bps` **1490** (floored);
- reconciliation waterfall with 12957 explained: process_error 8202, damage 5468, theft +713 → buckets sum to **27340** with zero drift;
- chargeback of 38871 → TIER_1, gross 31097, credit 4665, net 26432 (credit keyed on the gross tier, never re-tiered);
- store posture ladder (`PROBATION` at 9500 bps), promising gate, shrink-rate divergence (provisional vs final), OCC 412s, SoD 403, blackout 409, `ERR_RECOUNT_REQUIRED` at the `>=` boundary, pagination 422, unauthenticated 401, 404s.

Server was killed by the exact PID owning the port (`ss -ltnp` → `kill <pid>`); no broad `pkill` was ever run, and both test ports are free. `__pycache__` removed; no seeded data and no on-disk persistence anywhere.

## Step 5: Generate Unit Tests — 2026-09-03T17:34:00.000Z

All generation and verification is complete. Final state below.

## Files written

**`test_helpers/` — 9 files, 2,349 lines**
`api_client.py` 523, `fixtures.py` 543, `factories.py` 374, `types.py` 229, `assertions.py` 225, `api_errors.py` 167, `constants.py` 165, `test_users.py` 98, `__init__.py` 25.

**`test_suite/` — 16 files, 8,311 lines, 207 tests**

| file | lines | tests | queue |
|---|---|---|---|
| conftest.py | 30 | — | fixtures `api`, `clock_at_default` |
| test_accuracy_and_variance_valuation.py | 290 | 9 | A |
| test_adjustment_authority_and_posting.py | 488 | 15 | A |
| test_derivation_cascades.py | 327 | 10 | A |
| test_tagging_and_vendor_money.py | 306 | 8 | A |
| test_window_geometry_and_precedence.py | 346 | 8 | A |
| test_physical_inventory_geometry_and_certification.py | 289 | 7 | A |
| test_reference_frame_entities.py | 495 | 15 | B |
| test_lifecycle_transitions.py | 494 | 12 | B |
| test_valuation_arithmetic.py | 815 | 18 | B |
| test_validation_rules.py | 573 | 14 | B |
| test_endpoint_surfaces.py | 724 | 18 | B |
| test_error_catalogue_access.py | 624 | 14 | B |
| test_error_catalogue_workflow.py | 939 | 24 | B |
| test_role_boundaries.py | 910 | 24 | B |
| test_concurrency_and_visibility.py | 661 | 11 | B |

Queue A (Difficulty): **57 tests**. Queue B (Corner): **150 tests**.

## Coverage audit

- **Difficulty §1.8: 23/23 non-stub instances covered** (0 stubs in the file), 1–4 tests each; the heaviest are `resource_temporal_overlap/overhead_reader_pool_aggregate_capacity_exceeded` and `physical_inventory_closed_interval_blackout_buffer` at 4 apiece.
- **Corner §1.9: 74/77 non-stub instances covered** (34 stubs excluded): calculations 8/8 (18 tests), consistency_model 1/1 (2), cross_cutting_complexity_layers 4/4 (9), endpoints 7/7 (18), entities 13/15 (15), errors 13/14 (38), rbac 9/9 (24), state_machines 12/12 (12), validations 7/7 (14).

## Skipped instances (3, all non-unique-derivability — none for PRD silence)

- `entities/item_system_fields_input_ignored` — the PRD never states that client-supplied system fields are silently ignored rather than rejected; both outcomes are consistent with §2.9.
- `entities/stock_position_computed_fields_input_ignored` — same defect.
- `errors/count_submit_without_a_covering_shrink_period_rejected` — the instance asserts a 409 on a zero-variance submit, but §3.5 says "A task on which every line is within tolerance needs no covering period at all", so the asserted rejection contradicts the contract.

## Verification run

- `ast.parse` sweep over `test_suite/*.py` + `test_helpers/*.py`: **ALL 25 FILES PARSE OK**.
- Tag audit: 207 tagged tests, **0 untagged, 0 dual-tagged, 0 tags pointing at nonexistent or stub instances**, every `Design:` line the last line of its docstring.
- Verbatim-quote audit against `workspace/PRD.md`: **0 non-verbatim quotes**. This session's sweep initially found 8 pre-existing violations, now fixed: one lower-cased sentence opener (`test_adjustment_authority_and_posting.py`), two elided `...` quotes and five quotes truncated mid-sentence with an invented full stop (`test_valuation_arithmetic.py`, `test_validation_rules.py`). Each was repaired by extending to the real PRD sentence boundary, which is the whole of the +27-line growth.
- Static reference check: every `f.*`, `fx.*` and `api.*` attribute used by all 15 test files exists in the helpers — **0 missing**.
- `pyflakes` over both directories: clean apart from the intentional re-exports in `test_helpers/__init__.py`.

Two notes for the caller: nothing under `workspace/implementation/` was read or written, and no sibling task directory was opened. The background implementation agent was left alone.

## Step 7: Run Tests and Iterate — 2026-09-03T17:13:00.000Z

Clean sweep achieved. My smoke port is free and no stray servers remain.

## Summary

**Iterations run:** 2 sweeps (8 parallel rounds each). Sweep 1: 195/207 in all 8 rounds, with the *same* 12 tests failing every round — fully deterministic, no load-induced flakiness. Sweep 2 after fixes: 207/207 in all 8 rounds.

**Tests deleted:** none. Every failing test survived STEP 1 — each cited a verbatim PRD sentence that uniquely determined the asserted outcome.

**Fixes applied to `test_helpers/`**
- `test_helpers/factories.py` — the four named SKU variants (`tee2_item_payload`, `pan_item_payload`, `sofa_item_payload`, `tv_item_payload`) forwarded their own `sku`/`unit_cost_cents`/`retail_price_cents` as literal keyword arguments *and* splatted `**overrides`, so any caller override of those fields raised `TypeError: got multiple values for keyword argument`. Extracted a `_item_variant` merge helper so caller overrides win. (Was killing `test_one_cent_past_the_ceiling_re_tiers_the_whole_calculation`, which needs a 50001-cent SOFA.)
- `test_helpers/api_client.py` — added an `ApiClient._request` override that renders boolean query values as `true`/`false`. Python's `False` was reaching the wire as `"False"`, which the PRD-faithful `superseded` filter correctly rejected with `ERR_INVALID_ENUM_VALUE` (§2.3 enumerates the accepted filter values). Fixed the client, not the server's check.

**Fixes applied to `test_suite/`** (payload values contradicting PRD §3.7)
- `test_concurrency_and_visibility.py` (5 sites) and `test_role_boundaries.py` (1 site) built adjustment payloads with `reason_code="THEFT"` / `"DAMAGE"` — those are investigation **root causes**, not adjustment reason codes. PRD §3.7: "`reason_code` is one of `COUNT_VARIANCE`, `NEGATIVE_CORRECTION`, `PHANTOM_CLEAR` or `PHYSICAL_RECONCILIATION`". The impl was right to answer `ERR_INVALID_ENUM_VALUE` (priority 6) ahead of the `ERR_STALE_STOCK_POSITION_VERSION` the tests expected (priority 7). Switched to `COUNT_VARIANCE`, which preserves each test's meaning (the two affected tests assert `approval_state == "PENDING"`, i.e. the ladder must run — so the exempt codes would have been wrong).

**Fixes applied to `implementation/`**
- `workspace/implementation/db.py` + `calc.py` (`touch`, `base_row`) — `created_at`/`updated_at` were stamped from `datetime.now()`, directly contradicting PRD §2.4 "Time in this domain is never read from the wall clock." Added `row_stamp_iso()` reading `db.clock`; row stamps keep the three-fractional-digit spelling §2.4 pins for those two fields. `meta.api_request_timestamp` stays on the wall clock (transport metadata, not a domain date rule).
- `workspace/implementation/db.py` (`format_clock_instant`, used by `clock_now_iso`) — fields stamped with "the current logical-clock instant" (`current_utc`, `posted_at`, `reversed_at`, `certified_at`, `last_counted_at`) now carry the clock's own spelling, omitting a zero fractional part. PRD §2.4 pins three fractional digits for `created_at`, `updated_at` and `api_request_timestamp` *only*, and says the clock "reads exactly `2026-08-01T00:00:00Z`" — so a `.000` suffix on the clock echo was not the contract spelling.

**Final sweep evidence:** results.1–8.json all `passed 207 / total 207`.

**Orchestrator verification:** independently parsed all 8 `results.*.json` (mtime 17:12) — every file reports `passed 207 / total 207`, and the suite is still 207 tests (0 deletions, consistent with the report). Step 8 is NOT skipped: Step 7 applied 2 `implementation/` fixes plus test_suite/test_helpers fixes.

## Step 8: Finalize PRD — 2026-09-03T17:26:00.000Z

File is intact end to end. Done.

## Result

`workspace/PRD_FINALIZED.md`

**Line counts:** PRD.md 567 → PRD_FINALIZED.md 567 (0.0% line delta; 122825 → 123856 bytes, +0.84%). Two lines revised in place, no lines added, no new sections.

### Changes

- **§2.4 (line 100)** — revise — added `created_at`/`updated_at` to the list of instants the logical clock supplies; named `api_request_timestamp` as the sole real-time reading; pinned the two coexisting spellings (row stamps always 3 fractional digits; `current_utc`/`last_counted_at`/`posted_at`/`reversed_at`/`certified_at` echo the clock's own spelling, omitting a zero fractional part) — `implementation/db.py:76-120` (`format_instant`, `format_clock_instant`, `wall_now_iso`, `row_stamp_iso`, `clock_now_iso`), `implementation/calc.py:99-128` (`touch`, `base_row`).
- **§2.3 (line 92)** — revise — pinned the `superseded` list filter's accepted values as exactly the lowercase literals `true`/`false` — `implementation/validate.py:222-229` (`filter_bool`).

### Per-edit pre-edit search log

**Edit 1 — §2.4 timestamps**
- (a) Subject: the source and the textual spelling of every ISO instant the server writes.
- (b) Paths enumerated (grepped `datetime.now|format_instant|format_clock_instant|wall_now_iso|row_stamp_iso|clock_now_iso|isoformat` and `"created_at"|"updated_at"|posted_at|reversed_at|certified_at|last_counted_at|current_utc` across all of `implementation/`): `db.py:76/82/98/103/114/119/123` (the five formatter/reader helpers); `calc.py:101` (`touch`) and `calc.py:118-128` (`base_row`) — the only two writers of `created_at`/`updated_at`, both via `row_stamp_iso`; `calc.py:646` (`post_adjustment` → `posted_at`), `calc.py:659` (`reverse_adjustment` → `reversed_at`), `routes_positions.py:155` and `:176` (integrity-scan auto-posted `posted_at`, both branches), `routes_physical.py:346` (`certified_at`), `routes_physical.py` reconcile path (mints + posts via `calc.post_adjustment`, so it inherits the same `posted_at` spelling), `routes_counts.py:389/396` (`last_counted_at`), `routes_reference.py:317` (`current_utc`) — all via `clock_now_iso`; `response.py:23` (`api_request_timestamp` via `wall_now_iso`) — the only remaining `datetime.now` consumer; `routes_reference.py:228` (CounterFirm row exposing `created_at` only); `routes_counts.py:184-185` (`window_start`/`window_end` stored as the client's verbatim strings) and the calendar-date writers `routes_counts.py:81-82/480`, `calc.py:308-314`, `routes_physical.py:60-61`, `routes_shrink.py:66-67`.
- (c) Adjustments made to stay consistent with all of those: wrote "`created_at` and into `updated_at`" rather than "every resource's `created_at` and `updated_at`", so the CounterFirm row (no `updated_at`) is not mis-described; scoped the omit-zero-fraction rule to the five explicitly named clock-echo fields rather than to "every timestamp", so the client-echoed `window_start`/`window_end` and the `YYYY-MM-DD` date fields are untouched; phrased the exception as `api_request_timestamp` specifically instead of a general "envelope metadata" carve-out.

**Edit 2 — §2.3 `superseded` filter**
- (a) Subject: accepted wire values for boolean-valued query filters.
- (b) Paths enumerated: `validate.py:222-229` (`filter_bool` — accepts only `"true"`/`"false"`, treats absent/empty as no filter, else `ERR_INVALID_ENUM_VALUE`); grepped `filter_bool` across `implementation/` — one and only one callsite, `routes_physical.py:211` (`superseded` on the physical-inventory-line list); checked the sibling filter helpers `filter_enum:211`, `filter_int:232` (`pass_round`), `filter_str:243`; checked the body-side boolean path `validate.py:113-116` (`kind == "bool"` requires a real JSON boolean — a different code path from query filters, used by `auto_correct_negative`, `tag_required`).
- (c) Adjustment made: scoped the sentence to the `superseded` filter alone rather than to "boolean filters" or "booleans" generally, so it neither over-claims about `pass_round` (integer-valued, any parseable integer accepted) nor bleeds into request-body boolean validation, which requires a JSON `true`/`false` literal and reports `ERR_INVALID_REQUEST`.

**Step 7 items that produced no PRD edit:** the `test_helpers/factories.py` kwarg-collision fix (pure fixture bug — the 50000-cent `TIER_1` boundary it unblocked is already pinned in §3.8 step two); the `test_suite` `reason_code="THEFT"/"DAMAGE"` payload fixes (§3.7 already enumerates the four adjustment reason codes and §2.9 already ranks enum membership at 6 ahead of version match at 7, so the impl's answer was uniquely determined).

## Step 9: Complete PRD — 2026-09-03T18:05:00.000Z

Run as **three sequential file-partitioned passes** over a single `workspace/PRD_COMPLETED.md` (orchestrator decision, recorded here per the autonomy directive): a single subagent scanning 3600 lines of implementation against a 567-line PRD reliably under-scans and can leave the output byte-identical to its input. Partition: pass 1 = cross-cutting core (`app.py`, `db.py`, `errors.py`, `response.py`, `middleware.py`, `validate.py`, `calc.py`); pass 2 = `routes_reference.py`, `routes_positions.py`, `routes_tags.py`; pass 3 = `routes_counts.py`, `routes_investigations.py`, `routes_shrink.py`, `routes_physical.py`. Passes 2 and 3 were explicitly told the file already existed and carried prior passes' edits, so neither re-copied it from `PRD_FINALIZED.md`.

**Totals: 57 changes — 44 ambiguity-pins, 13 mismatch-revisions.** 567 lines → 567 lines (all in-paragraph, no new sections, no line-count change); 123,856 → 139,533 chars (+15,677, +12.7%).

### Pass 1 — core (23 changes: 17 ambiguity-pins, 6 mismatch-revisions), 130,531 chars
- §2.1 — insert — ambiguity — both headers trimmed before use; whitespace-only value counts as empty and 401s — `middleware.py:24-33`
- §2.1 — revise — mismatch — VendorRep scope compares the tag batch's own `vendor_id` (or body `vendor_id` at creation); there is no path-vendor case — `routes_tags.py:34-35`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 chars from uppercase letters and digits — `response.py:16-17`
- §2.2 — insert — ambiguity — unknown path, wrong method and any unhandled failure all return the error envelope with `ERR_INVALID_REQUEST` (422) — `app.py:47-60`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` draws `ERR_INVALID_PAGINATION`; empty string treated as omitted — `response.py:82-103`
- §2.3 — revise — **mismatch** — list ordering was "ascending `created_at`"; impl sorts **newest-first descending**, monotonic insertion sequence breaking ties (unavoidable, `created_at` comes off the logical clock) — `calc.py:114-115` + every `_list` helper
- §2.3 — insert — ambiguity — a §4 filter supplied as an empty string is treated as absent — `validate.py:211-247`
- §2.3 — insert — ambiguity — `pass_round` is not a closed enum: any integer accepted; non-integer draws `ERR_INVALID_ENUM_VALUE` — `validate.py:232-240`
- §2.4 — insert — ambiguity — every optional `note` is capped at 2000 chars, validated, then discarded — never persisted or returned — all `routes_*.py`
- §2.4 — revise — ambiguity — instant parsing accepts trailing `Z`, `+00:00`, or a naive string read as UTC; non-zero offset or unparseable text draws `ERR_INVALID_REQUEST` — `validate.py:147-161`
- §2.6 — insert — ambiguity — 2-dp is a quantization rule, not a wire format (100.00 serializes `100.0`, 87.50 → `87.5`); `min_accuracy_pct` accepts number or numeric string, >2 dp draws `ERR_INVALID_REQUEST` — `response.py:33-34`, `validate.py:117-130`
- §2.7 — revise — **mismatch** — server re-derivations bump `updated_at`/`version` only when recomputed figures actually change; enumerated the unconditional-bump exceptions (adjustment request/post/reverse, integrity scan, period-once-per-reconcile, accelerated schedule) and the never-bump case (unchanged tag batch) — `calc.py:99-102, 287-347, 375-405, 487-499`
- §2.9 tier 3 — insert — **mismatch** — tier 3 only runs this early when the scope target is named directly in the request (tag-batch body `vendor_id`); elsewhere the path identifier resolves first, so its 404 precedes `ERR_IDENTITY_SCOPE_VIOLATION` — `routes_tags.py:97-98`, `routes_counts.py:228-229`, `routes_physical.py:33-36`
- §2.9 tier 6 — revise — ambiguity — body must parse as a JSON **object**; explicit JSON `null` counts as absent — `validate.py:28-38, 60-66`
- §3.2 — revise — ambiguity — the restriction gate follows the position recorded on the investigation when opened, so a non-terminal investigation whose count line was deleted still restricts; `promising_reason` empty when `PROMISABLE`, else names the first matching sub-clause in a pinned order — `calc.py:192-210`, `routes_counts.py:352`
- §3.6 — insert — ambiguity — hop four leaves an unchanged tag batch's `updated_at`/`version` alone — `calc.py:497-499`
- §3.7 — insert — ambiguity — `value_impact_cents` is computed even on exempt rows; exemption skips only the threshold test and the step-7 comparison — `calc.py:613-619`
- §3.7 — revise — **mismatch** — hop five fires only on a transition **into** `SUSPENDED`; an already-suspended store is not re-accelerated — `calc.py:332-333`
- §3.7 — insert — ambiguity — the scan's PENDING branch is not exempt: full threshold ladder, no linked investigation, forced to `PENDING` — `routes_positions.py:149-151`, `calc.py:608-621`
- §3.7 — insert — ambiguity — a second, no-op scan still bumps the position's `version` — `routes_positions.py:184`, `calc.py:301-302`
- §3.8 — revise — **mismatch** — final close forces `unresolved_cents` to 0 permanently, discarding waterfall residue and shrinking `total_attributable_variance_cents` by it — `calc.py:396`
- §3.10 — insert — ambiguity — pinned the `demotion_reason` clause order across all five sub-clauses — `calc.py:244-255`
- §4 preamble — revise — ambiguity — the two vendor-chargeback endpoints answer 201 despite minting no resource; everything else answers 200 — `routes_shrink.py:255, 281`

Pass 1 left alone: the 69-id §5 catalogue (scripted check — zero set difference, zero status mismatch), §2.5/§2.9 tier-7 stale-version ordering (verified across all three write paths), §3.9 line arithmetic, `start.sh`/`requirements.txt` (nothing PRD-observable).

### Pass 2 — reference/positions/tags (16 changes: 12 ambiguity-pins, 2 mismatch-revisions across 14 lines), 135,322 chars (+4,791)
- §2.3 — insert — ambiguity — every list filter is spelled exactly as the resource field it matches, never a shortened alias; an identifier matching no row selects nothing rather than erroring — `routes_positions.py:242`, `routes_reference.py:298`, `routes_tags.py:75`
- §2.6 — revise — **mismatch** — `min_accuracy_pct` with >2 decimals is rejected *unless integral*, whose trailing zeros are tolerated (`100.000` accepted, `95.250` rejected); range test precedes quantization — `routes_reference.py:52` via `validate.py:117-130`
- §2.8 — insert — **mismatch** — a *required* body FK absent or explicit `null` raises that type's 404 at tier 5 and never reaches tier 6's `ERR_INVALID_REQUEST`; `investigation_id` is the sole optional body FK, skipped when absent/null — `routes_positions.py:43-44,216`, `routes_reference.py:266-267`, `routes_tags.py:36-38`
- §3.1 — insert — ambiguity — store/vendor/counter-firm/`sku` codes carry no character-class restriction (unlike a category code); uniqueness is exact case-sensitive string compare — `routes_reference.py:29-32,94`
- §3.2 — insert — ambiguity — the position row carries `promising_reason` beside `promising_state`, empty at creation, which can only land `PROMISABLE` — `routes_positions.py:70-76`
- §3.3 — insert — ambiguity — `required_sample_units` reads 0 and `encoding_scheme`/`epc_prefix` read null on a `DRAFT` batch — `routes_tags.py:44-57`
- §3.3 — insert — ambiguity — a `VendorRep` omitting body `vendor_id` gets `ERR_IDENTITY_SCOPE_VIOLATION` (tier 3) while a `SystemAdmin` gets `ERR_VENDOR_NOT_FOUND` — `routes_tags.py:34-36`
- §3.3 — insert — ambiguity — a non-string/empty/non-digit `epc_prefix` is `ERR_INVALID_REQUEST` at tier 6, ahead of the state check and `ERR_TAG_SCHEME_MISMATCH` — `routes_tags.py:100` / `validate.py:101-104`
- §3.3 — revise — ambiguity — encode accepts `DRAFT` and nothing else; the misleading "or … not in `VERIFICATION_FAILED`" parenthetical now points at the rework step — `routes_tags.py:103-104,192-193`
- §3.3 — insert — ambiguity — all four sample counts are non-optional integers ≥ 0 — `routes_tags.py:131-136`
- §3.3 — insert — **mismatch** — the vendor row's `updated_at`/`version` are refreshed by *every* verification even when the clamp leaves score and band unchanged; with no position for that store+SKU the verification still succeeds — `routes_tags.py:170-171,178-182,166`
- §3.3 — insert — ambiguity — `encoding_scheme` and `epc_prefix` survive a rework untouched — `routes_tags.py:197-206`
- §3.7 — insert — ambiguity — `approved_by_user_id`, `posted_at`, `reversed_at` read null on a fresh adjustment — `calc.py:633-635`
- §3.7 — insert — ambiguity — the four post preconditions are listed in reading order, not evaluation order — `routes_positions.py:296-309`
- §3.7 — insert — ambiguity — reversing a `NEGATIVE_CORRECTION` never decrements `negative_correction_count` — `routes_positions.py:324` / `calc.py:656-664`
- §3.7 — insert — ambiguity — the integrity scan parses no body at all, so a broken payload cannot make it fail — `routes_positions.py:132-136`

Pass 2 left alone: all §4 role rows and HTTP codes for its 30 endpoints (verified identical to impl); the `/accuracy`, `/fulfillment-eligibility` and integrity-scan response field sets; `read_rate_bps`'s unreachable divide-by-zero branch; the absence of a segregation guard on `/post` and a tag-hold guard on `/reverse` (both already pinned by §2.1 / §2.9 tier 9).

### Pass 3 — counts/investigations/shrink/physical (18 changes: 15 ambiguity-pins, 3 mismatch-revisions), 139,533 chars (+4,211)
- §3.4 — insert — ambiguity — `RETIRED` is never assigned by any operation; it exists only as an accepted `status` filter value — `routes_counts.py:19,111-134`
- §3.4 — insert — ambiguity — a task's `window_start`/`window_end` are echoed back verbatim as the request spelled them, while the geometry compares parsed UTC instants — `routes_counts.py:184-194`
- §3.4 — insert — mismatch — the five count-line checks run in §3.4's stated order, not §2.9's tiers, so duplicate-line + unsupported read mode reports `ERR_DUPLICATE_COUNT_LINE` — `routes_counts.py:268-282`
- §3.5 — insert — ambiguity — an investigation is born with `assigned_investigator_id`, both root-cause fields, both user fields and `evidence_note` null, `proposal_round` 0 — `routes_counts.py:335-358`
- §3.5 — insert — ambiguity — return-to-count does **not** reset `in_scope_position_count`; the original start's denominator governs the recount — `routes_counts.py:429-442`
- §3.5 — insert — ambiguity — a void unwinds nothing beyond the lines and `counted_line_count`: coverage/variance rollups stand, no position/store re-derivation, no waiving — `routes_counts.py:485-497`
- §3.6 — insert — ambiguity — exact investigation payload field set; the line's position, SKU and task are internal and not returned — `routes_counts.py:335-358`, `routes_investigations.py:26-29`
- §3.6 — insert — ambiguity — `assigned_investigator_id` is a 1–200 character string — `routes_investigations.py:57`
- §3.6 — insert — ambiguity — returning a proposal leaves `evidence_note` standing — `routes_investigations.py:101-103`
- §3.6 — revise — ambiguity — the vendor-shortage hop resolves the SKU from the investigation's own frozen pointer, so it survives a deleted count line — `routes_investigations.py:151-159`
- §3.8 — insert — ambiguity — `active_variant` is the lowercase `final`/`provisional`; the /attribution read skips the final-close zeroing, so a `FINAL_CLOSED` period with waterfall residue still reports it — `routes_shrink.py:115-164`
- §3.8 — insert — ambiguity — each closure step and the reopen bumps `version` by exactly 1; a provisional close does not seal the buckets against a later count submit naming the period — `routes_shrink.py:30-35,171-209`
- §3.8 — revise — ambiguity — chargeback aggregation keys on the investigation's recorded SKU, not a re-read of the count line — `routes_shrink.py:216-229`
- §3.8 — insert — ambiguity — `credit_cents` must be strictly greater than 0 — `routes_shrink.py:273`
- §3.9 — revise — **mismatch** — supersede is within-pass only; an earlier `pass_round` line keeps `superseded` false (PRD had claimed cross-round supersede) — `routes_physical.py:118-128,159-188`
- §3.9 — insert — ambiguity — order-recount leaves the four valuation rollups carrying the completed pass's figures — `routes_physical.py:263-266`
- §3.9 — insert — **mismatch** — reconcile's two guards run in §3.9's order, not §2.9's, so `ERR_RECOUNT_REQUIRED` beats `ERR_NO_COVERING_SHRINK_PERIOD` — `routes_physical.py:288-298`
- §3.9 — insert — ambiguity — reconciliation adjustments stamp `requested_by_user_id` with the acting ShrinkController, not the literal `system` — `routes_physical.py:309-311`

Pass 3 left alone: schedule-creation reader-mode check order and count-line/submit precondition orders (already match §2.9 or §3.x); `resume` silently ignoring a `note`; cumulative waterfall allocation across two reconciliations into one period (§3.8 already covers it); the unreachable period-less-investigation branch.

### Orchestrator verification (independent of the subagents)
- `PRD_COMPLETED.md` is **not** byte-identical to `PRD_FINALIZED.md` — 51 changed lines, +15,677 chars. The Step 9 scan genuinely ran.
- File intact: 567 lines, §4 table still carries all **81** endpoint rows, §5 still carries all **69** error rows, tail ends on `ERR_CREDIT_EXCEEDS_BALANCE | 422` — a real section boundary.
- No `.py` file under `implementation/`, `test_suite/` or `test_helpers/` was modified after the green sweep at 17:12, so the `results.1..8.json` evidence of **207/207 in all 8 rounds** still describes the delivered artifact.

## Pipeline complete.
