# Worklog — task_2624_used_furniture_consignment_gallery_white_glove_pickup

## Step 1: Create task directory — 2026-09-03T21:02:19.680Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2624_used_furniture_consignment_gallery_white_glove_pickup` and its `workspace/` subdirectory. Index 2624 was pre-assigned by the invoking command; no scan of ./tasks/ was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-04T00:27:40.805Z

All three scaffold artifacts are complete and the lint is clean.

**Lint verdict (verbatim):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2624_used_furniture_consignment_gallery_white_glove_pickup/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2624_used_furniture_consignment_gallery_white_glove_pickup/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2624_used_furniture_consignment_gallery_white_glove_pickup/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    67
  §1.1 entities declared:     15
  §1.8 instances scanned:     19
  §1.9 instances scanned:     81
  Calls scanned (§1.8+§1.9):  1204

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2624_used_furniture_consignment_gallery_white_glove_pickup/`):

| file | lines | shape |
|---|---|---|
| `SCAFFOLD.yaml` | 3053 | §1.0–§1.7 + preamble; top keys `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` — no design keys |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2500 | single key `scaffold_difficulty_design`; **9 rule_ids / 19 instances** |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 5627 | single key `scaffold_corner_design`; **9 sections / 110 instances (81 with `test_recipe`, 29 `excluded_because`)** |

Corner-design breadth: entities 13, state_machines 10+6, calculations 8+7, validations 6+3, endpoints 6, errors 31+9, rbac 5, cross_cutting_complexity_layers 1+4, consistency_model 1. Scenario text is stored verbatim; 15 entities, 67 endpoints, 55 error ids, 7 roles, 44 ordered validations.

**Verified invariants:** all 110 corner names + 19 difficulty names are globally unique; every `excluded_because.difficulty_instance` (25 of them) resolves to a real §1.8 instance name; all 55 §1.6 error ids are asserted somewhere (46 in §1.9, the other 9 inside the §1.8 instances they are delegated to); the in-file 55-row error coverage comment table's 16 cross-references all resolve to existing instance names.

**Design adjudications**
1. Two stale foreign design files from an abandoned generation were overwritten; the stale corner file is preserved at `/tmp/STALE_CORNER_2624.yaml`.
2. Swapped validation p38/p39 so the zero-or-negative test runs before the 2000-cent minimum — otherwise `ERR_INSUFFICIENT_BALANCE` was unreachable; the §1.8 instance was renamed `escheated_state_p11_beats_payout_minimum_p39`. Both gates now have paired corner instances (balance −350 → insufficient, +118 → below minimum).
3. Added the grade rank ladder (A=4, B=3, C=2, D=1, REJECTED=0) to §1.2 and §1.5 so a D→REJECTED receiving inspection is a one-grade drop landing in `AWAITING_PLACEMENT`; that is what makes `ERR_GRADE_REJECTED` reachable at placement.
4. **Scaffold repair this session:** the `SCREEN_ACCEPTED` transition required `photo_count >= 4` while validation p26 and the `ERR_PHOTOS_INSUFFICIENT` catalog entry both say 3. Changed the precondition to `photo_count >= 3` (SCAFFOLD.yaml line 881) and pinned the inclusive boundary in the corner instance (2 refused, 3 grades to A at 51000).
5. `interval_merge` and `ops_run_checkpoint` have no applicable row/realisation: truck overlap is validation p21 rather than a calculation, and the guide's layer table has no `ops_run_checkpoint` row, so no claim_type was invented — the ops-run content is carried by the calculations instance `the_markdown_run_skips_pieces_that_were_never_placed`, with an explicit YAML comment recording the decision. `derived_field_reconciliation` is realised as the calculations threshold instance on zone utilization.
6. Declared values were raised where needed so no placed price falls under the 50000 clearance threshold (avoiding stray `clearance_relocation_pending` side effects); where a sub-threshold price is unavoidable (the 850 Trinket payout fixture) the piece is placed directly into a `CLEARANCE` zone.
7. `role_model` is `segregation_of_duties`, so the rbac walk covers the two general Table 7 rows plus all three declared segregation sites (screened item, counted audit, scheduled delivery) and drops a `peer_roles` instance rather than borrowing a claim_type the profile does not declare.
8. Negative instances are named `..._is_refused` on purpose so the lint's `_NEGATIVE_NAME_RE` escape hatch does not silence checks (b)/(c); the escape is used only where required — the `ERR_UNAUTHENTICATED` instance (no header sent) and the `_cannot_` RBAC denials whose acting role is deliberately outside the endpoint's role list.
9. Claim-type spellings were normalised to snake_case across all 110 instances (12 edits) after the guide's row labels were transcribed with mixed casing.

## Step 3: Copy shared files — 2026-09-04T00:28:03.791Z

Copied `./INSTRUCTION.md` to `tasks/task_2624_used_furniture_consignment_gallery_white_glove_pickup/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T00:43:38.140Z

**PRD generated:** `/home/ubuntu/github/CodingPRD/tasks/task_2624_used_furniture_consignment_gallery_white_glove_pickup/workspace/PRD.md` — 489 lines, 15,778 words. Ends at a real boundary (last row of the §5 error table); no audit footer written into the file.

**Structure (5 top-level sections):**
- §1 Introduction
- §2 Global Specifications & System-Wide Principles — 11 subsections: 2.1 Operator Identity and RBAC, 2.2 API Response Structure (verbatim canonical block, byte-identical), 2.3 Pagination, 2.4 Resource Identity/Timestamps/Version Counters, 2.5 The Logical Clock and the Two Nightly Epochs, 2.6 Money, Rounding and the Pinned Order of Arithmetic, 2.7 Stale-Read Protection on Payouts and Write-Offs, 2.8 Segregation of Duties, 2.9 The Order in Which a Request Is Rejected, 2.10 Floor Zone Occupancy and the Utilization Band, 2.11 The Consignor Payout Ledger
- §3 Business Logic & Workflows — 9 subsections (standing records; agreements/intake; photo screening, grading and opening ticket price; pickup routing, surcharge quoting, custody transfer; receiving inspection, grade divergence, dispute election; placement, tagging, clearance relocation; markdown epoch, unsold flag, disposition election loop; sale, split, delivery, damage adjudication; shrinkage, write-offs, payouts, escheatment)
- §4 Endpoint Definitions — 67 endpoints, 4-column table (Method, Path, Description, Authorized Role(s))
- §5 Error Code Catalogue — 55 errors, 2-column table (Error ID, HTTP Status Code)

**Coverage audit:**
- Endpoints: 67/67 in §4
- Errors: 55/55 in §5 table *and* all 55 also narrated in §1–§3 prose
- Validations: 44/44 — the priority ladder rendered as an explicit ordered rejection sequence in §2.9 (39 ladder positions with every `applies_to` set enumerated, plus 5 endpoint-local rules: agreement must be DRAFT, pickup job must be SCHEDULED, audit must be COUNTED, schedule ACTIVE/RETIRED, email uniqueness — noted as having unobservable absolute ladder position)
- State machines: 9/9, 52/52 transitions (ConsignmentItem `lifecycle_state` 17 values/25 transitions; ConsignmentItem `inventory_state` 5 values/6 transitions; plus agreement, pickup job, sale, delivery order, damage claim, shrinkage audit, Consignor `escheat_state`)
- Calculations: 14/14 fully expressed in natural language (no symbolic operators, no pseudocode)
- OCC rules: 2/2 with write_endpoint + guard field + error_id + 412 all named
- Field names: 124/124 entity fields, 63/63 request-body identifiers, 20/20 query params, all in backticks

**Zero-Silence decisions (scaffold self-contradictions; one reading chosen and documented):**
1. Sale register floor — state machine said 0.90, validation 36 and the `ERR_SALE_BELOW_FLOOR` condition said 0.80 → wrote **80 hundredths of current price**.
2. `DISPOSAL_FEE_DEBIT` amounts — state machine: RETURNED −4000 / DONATED −2500; release endpoint: DONATED −3500 / RETURNED none → wrote the **state-machine pair (return 4,000 cents; donation 2,500 cents)**.
3. DISCOUNT election repricing — state machine said 80% of current price floored at `min_price_cents`; the `discount_elected` calculation variant and the endpoint said re-run markdown_price with the extra 10% → wrote the **calculation variant (extra ten-percent cut on the stepped price, floor applied after)**.
4. `placement_zone_id` at sale — state machine released it at sale; sales and delivery-complete endpoints retained it until delivery → wrote **retained until delivery** (sold-but-undelivered pieces still count toward `occupied_sqft`).
5. Placement pricing — state machine assigned `current_price_cents := list_price_cents` with `markdown_sequence := 1`; endpoint said run markdown_price → wrote the reconstructible form (first placement has `days_on_floor` 0, the sequence-1 step at offset 0 governs, sequence becomes 1, price is list price reduced by that step's `markdown_pct` then raised to its `min_price_cents` if below).
6. Tenure penalty threshold — a state-machine note said sequence ≥2 "can trigger"; `TENURE_PENALTY_SEQUENCE: 3` → wrote **3 or higher**.
7. Lot parent grade — ladder was A>B>C>D with no REJECTED rank → wrote "lowest grade among components, `A` highest through `D` lowest" without inventing a REJECTED position.
8. `ERR_ELECTION_ROUND_EXHAUSTED` scope — validation 18 covers any DISCOUNT election, but the RECEIVING_DISPUTE DISCOUNT edge carries no `election_round` precondition → stated the limit as validation 18 does and explicitly noted a dispute-path DISCOUNT leaves `election_round` unchanged.

**Hard Contract reports:**

```
Field coverage check:
- entities[].fields: 124 required, 124 present, 0 missing
- endpoints[].request_body: 63 required, 63 present, 0 missing
- endpoints[].query_params: 20 required, 20 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 44 checked, 44 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + error_id all named), 0 missing
- state_machines[].transitions: 52 checked, 52 fully expressed, 0 missing
- calculations[]: 14 checked, 14 fully expressed, 0 missing
- validations[] conditions: 44 checked, 44 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 67 checked, 67 expressed, 0 missing
- entities[].fields[] structured content: 124 checked, 124 reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked (screen ACCEPT/REJECT, receive <=1-grade/>=2-grade, pickup complete COMPLETED/FAILED, delivery DELIVERED/REFUSED/CANCELLED, adjudicate approve true/false, audit variance zero/nonzero), 6 with equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 1036
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Additional clean checks:** 0 missing state/enum values; 0 fuzzy words (approximately/roughly/around/~); 0 pseudocode operators (`>=`, `<=`, `!=`, `==`, `round_half_up`, `min(`, `max(`, `ceil(`, `floor(`, ` AND `, ` OR `) in prose outside code fences; all 7 role names present; all 9 ledger `entry_type` values present.

**Constraints honored:** neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced; no sibling task directory was read; PRD.md was built via 8 chunked appends (6 heredocs + 2 Python appends), never a single giant Write.

**Orchestrator truncation check:** `tail -15` shows the file ending on the final `ERR_DUPLICATE_EMAIL | 409` table row; all five top-level sections present. Not truncated — no regeneration needed.

## Step 6: Generate implementation — 2026-09-04T01:14:00.000Z

(Steps 5 and 6 were launched concurrently in a single assistant message, so the impl generator could not see `test_suite/`; Step 6 returned first and is logged first.)

Implementation complete and verified.

## Files written — `tasks/task_2624_used_furniture_consignment_gallery_white_glove_pickup/workspace/implementation/`

| file | lines | role |
|---|---|---|
| `start.sh` | 10 | guarded `pip install` (only when Flask is missing) + `exec python3 app.py` |
| `requirements.txt` | 1 | `Flask==3.0.3` |
| `app.py` | 56 | app factory, 7 blueprints, `ApiError`/`HTTPException`/catch-all envelope handlers, `0.0.0.0:$PORT` (default 10000) |
| `store.py` | 135 | 15 in-memory dict collections, logical clock (origin `2026-08-01T00:00:00Z`), `new_row`/`touch`/`ordered`, day arithmetic |
| `errors.py` | 81 | 55-id catalogue → HTTP status, `fail()` |
| `envelope.py` | 57 | `meta`/`response_type`/`data`, `req_` + 20 uppercase alnum id, pagination meta |
| `auth.py` | 53 | header identity, 7 roles, consignor/buyer ownership scoping |
| `validation.py` | 199 | typed field readers, pagination, `raw_fk` pre-schema FK pass, `lookup` |
| `calc.py` | 318 | all 14 declared calculations, `Decimal` + ROUND_HALF_UP, two-step pinned rounding |
| `services.py` | 279 | derived figures, append-only ledger `mint_entry` (balance/suspension/dormancy cascade), pricing + lot + clearance cascades |
| `serializers.py` | 284 | one serializer per entity, computed fields recomputed at read time |
| `routes/standing.py` | 219 | consignors, payout waterfall, buyers |
| `routes/schedules.py` | 221 | price schedules, steps, agreements |
| `routes/items.py` | 495 | intake, screen, receive, place, elect-disposition, inventory-flag, write-off, release |
| `routes/logistics.py` | 369 | trucks, crews, floor zones, pickup jobs |
| `routes/commerce.py` | 466 | sales, delivery orders, damage claims |
| `routes/audits.py` | 143 | shrinkage count + batch write-off approval |
| `routes/ops.py` | 158 | clock, markdown epoch, escheatment epoch |
| **total** | **3544** | |

## Endpoints
**67 implemented — an exact 1:1 set match against the scaffold's 67 (method, path) pairs; zero missing, zero extra** (diffed programmatically against `SCAFFOLD.yaml`).

## Verification
- `python3 -m py_compile` on all 17 `.py` files: clean.
- Every file `wc -l`'d and `tail`'d; all end at real code boundaries.
- No SQLite, no `open()`, no JSON on disk, no `/tmp` — grep-confirmed; nothing is seeded, and the store starts empty with the clock at its origin.
- Fresh boot via `start.sh` answers requests in **0.78 s** (`start.sh` needed `chmod +x`, now `-rwxrwxr-x`).

## Smoke tests (two scenarios, 60+ calls, every status asserted)
1. **Happy path + refusals:** consignor → schedule → 2 steps → agreement activate → 2 items screened → truck/crew → pickup job (+attach, complete, surcharge debit −35000) → 2 receiving inspections → zone → placements → sale (floor enforced: `ERR_SALE_BELOW_FLOOR` on price 1) → delivery order → DELIVERED (sale SETTLED, item SETTLED/RELEASED, claim window opened) → claim → segregation 403 on the booking coordinator → request-info → resubmit → adjudicate CONSIGNOR → shrinkage audit (segregation 403 for the counter, then approve → SHRINKAGE_CREDIT) → clock non-monotonic 422 → both epochs → payout → unknown path 404. **SMOKE OK.**
2. **Markdown chain:** list 147000 → step 2 = 117600 → step 3 = 73500 (floor respected), `ON_FLOOR → MARKED_DOWN → UNSOLD_PENDING_ELECTION` at day 26 ≥ trigger 20, 45-minute truck turnaround conflict 409, receiving segregation 403, DONATE election → release → DONATED with a −2500 `DISPOSAL_FEE_DEBIT` (balance −22500) → payout refused `ERR_INSUFFICIENT_BALANCE`. **SMOKE2 OK.**

Both servers were killed by their own PID (ports 18624/18625 confirmed free); no broad `pkill` was ever issued.

Spec conflicts resolved in favour of the PRD as the literal contract: register floor 0.80 (not the scaffold's 0.90); DISCOUNT repricing as `list_price × (1−pct) × 0.90` then floor; `ERR_SALE_ALREADY_REVERSED` used for a non-`SCHEDULED` delivery order (no dedicated id exists); ladder followed positionally where the narrative order differs (truck conflict 21 before window-order 23, duplicate-tag 29 before zone-closed 32, custody 10 before sale-status 15, segregation 3 before audit state 42).

## Step 5: Generate unit tests — 2026-09-04T02:35:00.000Z

Generation complete for `task_2624_used_furniture_consignment_gallery_white_glove_pickup`.

## Files written

Both output directories are at the **task root**; `workspace/` contains only `INSTRUCTION.md`, `PRD.md` and the untouched `implementation/`.

`test_helpers/` (9 files, 2,851 lines): `__init__.py` 55, `api_client.py` 279, `api_errors.py` 124, `assertions.py` 531, `constants.py` 172, `factories.py` 333, `fixtures.py` 834, `test_users.py` 82, `types.py` 441.

`test_suite/` (`conftest.py` 55 + 25 test modules, 9,548 lines, **125 tests**):

| file | lines | tests |
|---|---|---|
| test_01_pickup_surcharge_settlement | 202 | 3 |
| test_02_grade_divergence_and_ticket_price | 220 | 4 |
| test_03_split_and_payout_formulas | 223 | 4 |
| test_04_item_state_dimensions | 167 | 3 |
| test_05_claim_negotiation_cycle | 161 | 3 |
| test_06_lot_cascade_and_clearance | 252 | 3 |
| test_07_sale_credit_cascade | 281 | 3 |
| test_08_rejection_precedence | 331 | 4 |
| test_09_boundary_precision | 366 | 4 |
| test_10_cross_entity_state | 412 | 4 |
| test_11_resource_windows | 400 | 4 |
| test_12_conservation_invariants | 466 | 5 |
| test_13_entities | 679 | 13 |
| test_14_state_machines | 701 | 10 |
| test_15_calculations | 801 | 8 |
| test_16_validations | 580 | 6 |
| test_17_endpoints | 689 | 6 |
| test_18_errors_lookup | 220 | 11 |
| test_19_errors_repeat_and_ordering | 301 | 6 |
| test_20_errors_intake_and_placement | 449 | 5 |
| test_21_errors_custody_and_counting | 304 | 3 |
| test_22_errors_claims_and_elections | 321 | 3 |
| test_23_errors_fiscal_gates | 256 | 3 |
| test_24_rbac | 450 | 5 |
| test_25_concurrency_and_consistency | 261 | 2 |

## Coverage

- **Queue A (Difficulty, §1.8): 19/19 live instances translated**, 44 tests, no missing / bogus / stub-tagged rule ids.
- **Queue B (Corner, §1.9): 81/81 live instances translated**, 81 tests — entities 13/13, state_machines 10/10, calculations 8/8, validations 6/6, endpoints 6/6, errors 31/31, rbac 5/5, cross_cutting_complexity_layers 1/1, consistency_model 1/1. `missing=[] bogus=[] stub_tagged=[]`, no orphan sections.
- **0 instances skipped.** Every non-stub instance in both indices has at least one test; stub instances (those carrying `excluded_because` instead of `test_recipe`) were never tagged.

## Two recipes overridden in favour of the PRD

- `errors/a_third_discount_election_on_one_piece_is_refused`: the recipe compounds the discount against `current_price_cents` (68,000 then 54,400). PRD §3.7 defines the discount-elected variant from `list_price_cents`, so the value is **76,500 in both rounds**; I asserted the PRD figure. The instance's actual claim (third `DISCOUNT` → `ERR_ELECTION_ROUND_EXHAUSTED`, `RETURN` still available) is unaffected.
- `consistency_model/the_sale_response_already_carries_the_split_and_the_freed_floor_space`: the recipe asserts `occupied_sqft == 0` and `placement_zone_id` null immediately after the sale. PRD §3.8 says the opposite in as many words — the zone is "deliberately **retained** until the piece physically leaves on a delivery". The test therefore asserts the footage still charged at the sale and then freed by the `DELIVERED` completion, which is where §3.8 puts it. Same reasoning applied to the recipe's incorrect register floor (`× 0.90`; PRD §3.8 says `× 80 hundredths`) — that figure is never asserted.

## Verification run

- `python3 -m py_compile` clean on all 34 generated `.py` files.
- `python3 -m pyflakes` silent on every test module and every helper (removed one genuinely unused import from `fixtures.py`; remaining warnings are only the `# noqa`-marked barrel re-exports in `test_helpers/__init__.py`).
- `pytest --collect-only`: **125 tests collected in 0.88s**, no collection errors.
- Citation checker: every `PRD n.n: "…"` quote is a verbatim ≥8-word substring of `workspace/PRD.md` — `citation problems: 0`.
- Section checker (maps each PRD line to its owning `##`/`###` heading and compares against the cited label) — `section problems: 0`.
- Tag checker: all 125 tests have exactly one `Design:` line and it is the last line of the docstring; no dual-tagged or untagged tests.
- No `pytest.mark.skip`, `skipif` or `xfail` anywhere; the word "scaffold" appears in neither directory.

**Orchestrator check:** confirmed `test_helpers/` and `test_suite/` are at the task root and `workspace/` holds only `INSTRUCTION.md`, `PRD.md`, `implementation/` — no test directories leaked under `workspace/`.

## Step 7: Run tests and iterate — 2026-09-04T02:57:00.000Z

Clean sweep verified. All 8 `results.$i.json` exist with mtime 02:47 and report 125/125.

## Summary

**Iterations run:** 2 (each an 8-round parallel `setsid` sweep, 125 tests, `per-test-server` isolation).

- Iteration 1: 117/125 in all 8 rounds — the same 8 tests failed deterministically in every round (no flakiness anywhere in the suite).
- Iteration 2: **125/125 passed in all 8 rounds.**

**Tests deleted:** none. Every failure traced to a test-artifact defect, not to a PRD-silent assertion.

**Fixes applied to `test_helpers/`**

- `fixtures.py` — `request_payout()`: now issues the disbursement and then reads the minted `PAYOUT_DISBURSEMENT_DEBIT` back from `GET /consignors/{id}/ledger-entries`. It previously assumed the payout POST echoes the ledger entry in `data`; PRD §2.2/§4 never pin whether the created entry or the updated consignor row is echoed (both readings are defensible), whereas PRD §3.9 does unambiguously place `withholding_cents` / `processing_fee_cents` / `net_payout_cents` on the entry and §4 declares the ledger read endpoint. Fixed the read path rather than weakening the two assertions — all money assertions (withholding 2,020; net 98,980; `amount_cents` −101,000; `balance_after_cents` 0) are retained verbatim. Repaired `test_withholding_band_is_read_off_the_balance_before_anything_is_taken` and `test_payout_debits_the_whole_available_amount_and_zeroes_the_balance`.

**Fixes applied to `test_suite/`**

- `test_13_entities.py` (2 sites) — removed a stray extra positional argument `LOGISTICS_COORDINATOR_ID` passed to `api_client.create_pickup_job(payload, headers)`; the call raised `TypeError` before any request was sent. Repaired `test_a_crew_of_seven_movers_is_refused_before_anything_is_quoted` and `test_the_job_counts_its_own_load_and_snapshots_the_residence`.
- `test_22_errors_claims_and_elections.py` (4 literals) — `election_deadline_at` expectations written as `"…T00:00:00Z"`; PRD §2.4 requires "an ISO 8601 UTC timestamp with three fractional digits", so the literals now read `"…T00:00:00.000Z"`. Repaired `test_a_third_discount_election_on_one_piece_is_refused`.
- `test_08_rejection_precedence.py`, `_escheated_account_left_holding_seven_hundred_and_one_cents()` + `test_the_escheatment_epoch_zeroes_the_balance_without_moving_the_clock_forward` — the builder booked a second shrinkage write-off *after* the escheatment run, and PRD §2.11 says every minted entry except an `ESCHEATMENT_DEBIT` **does** refresh `last_activity_at`; the later `SHRINKAGE_CREDIT` therefore legitimately moved the stamp to 2028-01-28. The stamp is now captured immediately after `run_escheatment_epoch()`, which is the only point at which the asserted rule ("escheating a balance cannot restart the dormancy curve") is observable.
- `test_08_rejection_precedence.py` (2 tests) — `assert disposition_election is None` after a refused election relaxed to "unchanged from the pre-request value". PRD never states the field's initial value (DEFAULT-VALUE SILENCE); `null` and `"NONE"` are both PRD-faithful, and the rule actually under test is that the refusal writes nothing. Repaired `test_a_closed_election_window_answers_before_donate_eligibility_is_tested` and `test_the_lapsed_window_refuses_a_return_the_piece_is_otherwise_entitled_to`.

**Fixes applied to `implementation/`:** none. No failure survived STEP 1/STEP 2 — the implementation was already PRD-faithful on all 125 rules, and no PRD-required check was removed or weakened.

**Orchestrator verification:** independently read all 8 `results.$i.json` — every round reports `passed=125, total=125`.

**Step 8 skip-condition adjudication (orchestrator):** the skip applies only when Step 7 ran zero iterations beyond the baseline (0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, 0 `implementation/` fixes). Here there were 2 iterations with fixes in both test layers, and two of those fixes were explicitly attributed to PRD silence (the payout-response echo shape and the `disposition_election` initial value). Step 8 therefore runs, with the caveat that `implementation/` was never edited, so any PRD edit must be a silence-pin rather than a mismatch-correction.

## Step 8: Finalize PRD — 2026-09-04T03:00:00.000Z

`PRD_FINALIZED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_2624_used_furniture_consignment_gallery_white_glove_pickup/workspace/PRD_FINALIZED.md`.

## Size
- PRD.md 489 lines / 111,018 bytes → PRD_FINALIZED.md 489 lines / 112,070 bytes. Line delta 0.0% (3 paragraphs revised in place); byte delta +0.95%.

## Changes (3)
- **§2.4 — revise — timestamp rendering generalized** beyond `created_at`/`updated_at`: every other timestamp-valued field (`last_activity_at`, agreement `effective_at`/`expires_at`, `listed_at`, `election_deadline_at`, pickup/delivery `window_start`/`window_end`, `sold_at`, `reversed_at`, `outcome_recorded_at`, `claim_window_ends_at`, ledger `effective_at`) renders UTC with three fractional digits, null while unset, and client-supplied windows are echoed normalised — `implementation/store.py:63` (`iso`), `implementation/serializers.py:20` (`_dt`), used at serializers.py:35, 85-86, 120, 123, 174-175, 205-206, 217, 223-224, 277.
- **§3.2 — revise — intake opening values now pin `disposition_election` `NONE`** as the sentinel held until a path records an election (hence the value still read after a refused election) — `implementation/routes/items.py:116`.
- **§3.9 — insert — payout response shape/status pinned**: the disbursement answers 200 OK with the updated `Consignor` row (balance 0) in `data`, not 201 with the minted entry; the entry and its three reporting fields are read via `GET /consignors/{id}/ledger-entries` — `implementation/routes/standing.py:155`, entry fields at `implementation/serializers.py:266-280`.

No edit for the `test_13_entities.py` TypeError (pure call-signature defect), the escheatment `last_activity_at` capture point (PRD §2.11 line 189 / §3.9 line 349 already pin it, and `services.mint_entry:171` matches verbatim), or the payout money assertions (PRD §3.9 already places the three columns on the entry).

## Pre-edit search log

**Edit 1 (§2.4 timestamps).** (a) Subject: serialized representation of every timestamp-valued field, not just the Step 7 `election_deadline_at` site. (b) Enumerated: `store.iso` (store.py:63) — the single formatter; `serializers._common`/`_immutable`/`_dt` and every call site (all timestamp keys listed above); `envelope._meta` `api_request_timestamp`; `store.parse_dt` (accepts arbitrary ISO input, converts to UTC) which is what makes client-submitted delivery/pickup windows come back normalised; `routes/ops.py:44` clock input parsing. Every path funnels through one formatter, none emits a date-only or epoch value. (c) Wording widened from "three fractional digits" alone to include the UTC normalisation and the explicit "null while unset" clause, so `window_start`/`window_end` echoes and the many nullable stamps (`listed_at`, `reversed_at`, `claim_window_ends_at`, …) are all covered rather than contradicted.

**Edit 2 (§3.2 `disposition_election` default).** (a) Subject: the lifetime of `ConsignmentItem.disposition_election` — initial value, every writer, every reader. (b) Enumerated by grepping the field across `implementation/`: writers — `routes/items.py:116` (intake, `"NONE"`), `routes/items.py:365` (election records `DONATE`/`RETURN`/`DISCOUNT`), `routes/ops.py:99` (lapsed election sets `DONATE`); readers — `services.discount_elected` (services.py:189, `== "DISCOUNT"`), `routes/ops.py:27` (`_WATCHED` version-bump snapshot), `serializers.py:124`. No path ever resets it to `NONE`, and `NONE` is not an accepted request `election` (`items.py:328` `ELECTIONS`). Also checked the refusal branches in `elect_disposition` (items.py:346-362) return before any write. (c) Wording deliberately says "the sentinel that field carries until some path actually records an election" rather than "until the consignor elects", so the markdown epoch's lapse-to-`DONATE` writer is not excluded; no claim was made that `NONE` is a submittable election value.

**Edit 3 (§3.9 payout response).** (a) Subject: HTTP status and `data` payload of ledger-minting operations, specifically `POST /consignors/{id}/payouts`. (b) Enumerated all `envelope.created`/`ok`/`empty` returns across `routes/` (grepped, 60+ sites) and, in particular, every entry-minting endpoint: payout `standing.py:155` → `ok(consignor)`; write-off `items.py:465`, inventory-flag recovery `items.py:430`, release `items.py:495` → `ok(item)`; audit approval `audits.py:143` → `ok(audit)`; sale `commerce.py:108` → `created(sale)`; reversal `commerce.py:156`, delivery outcome `commerce.py:281/292`, adjudication `commerce.py:466`; pickup completion `logistics.py:337/354`; both epochs `ops.py:106/158` → `envelope.empty()`. A `PayoutLedgerEntry` is never echoed by any write endpoint — only by the two ledger list reads (`standing.py:121`, `items.py:168`). (c) Wording scoped to the payout endpoint alone rather than asserting a general "minting operations never echo the entry" rule, to avoid a universal claim over paths Step 7 never exercised; the parenthetical "balance now 0" was verified against `serializers.consignor` recomputing `unclaimed_balance_cents` from the ledger (serializers.py:33, services.py:125).

## Step 9 execution plan (orchestrator decision)

A single-subagent full-implementation scan on a 3,544-line implementation and a 489-line PRD has previously produced a byte-identical PRD_COMPLETED.md — i.e. the scan silently never ran. Step 9 is therefore split into **three sequential file-partitioned passes**, each owning a disjoint slice of `implementation/` and each editing the same `PRD_COMPLETED.md` in place:

- Pass A — cross-cutting layer: `app.py`, `store.py`, `errors.py`, `envelope.py`, `auth.py`, `validation.py`, `calc.py`, `services.py`, `serializers.py` (creates PRD_COMPLETED.md from PRD_FINALIZED.md).
- Pass B — `routes/standing.py`, `routes/schedules.py`, `routes/items.py`.
- Pass C — `routes/logistics.py`, `routes/commerce.py`, `routes/audits.py`, `routes/ops.py`.

Passes are strictly sequential (never concurrent) because all three write the same file.

## Step 9: Complete PRD — 2026-09-04T03:28:29.246Z

Run as three sequential file-partitioned passes over `implementation/`, all editing the same `workspace/PRD_COMPLETED.md` in place (Edit tool only, never Write). **42 changes total: 30 ambiguity-pins, 12 mismatch-revisions.**

### Pass A — cross-cutting layer (`app.py`, `store.py`, `errors.py`, `envelope.py`, `auth.py`, `validation.py`, `calc.py`, `services.py`, `serializers.py`)

Created `PRD_COMPLETED.md` from `PRD_FINALIZED.md`. 489 lines/112,070 chars → 491 lines/117,101 chars (24 diff lines, 11 edits). Every pin empirically confirmed against a live server (port 18324, killed by pid). Programmatic check: `errors.CATALOG` (55) vs §5 table (55) — zero missing/extra/status-mismatched. **11 ambiguity-pins, 0 mismatch-revisions.**

- §2.1 — insert — blank/whitespace-only `X-User-ID` counts as absent (401); role match exact and case-sensitive — `auth.py:22-27`
- §2.1 — insert — ownership refusal is `ERR_UNAUTHORIZED` 403 evaluated after path existence (404 wins); on lists ownership narrows the set (so `total_count` reflects the narrowed set) rather than refusing — `auth.py:39-52`
- §2.2 — insert — `api_request_id` = `req_` + exactly 20 upper-case-alphanumeric chars — `envelope.py:10-14`
- §2.2 — insert — `api_request_timestamp` comes from the logical clock, not wall clock; an unmoved clock stamps `2026-08-01T00:00:00.000Z` on every response including errors — `envelope.py:17-21`
- §2.3 — insert — equal-`created_at`/`effective_at` ties break by insertion order, never by `id` — `store.py:125-135`, `services.py:113-122`
- §2.3 — insert — filter query params are exact, case-sensitive and unvalidated: an unrecognised value yields an empty page with 200, not `ERR_VALIDATION`; empty value ≡ absent — `validation.py:180-185`
- §2.4 — insert — client instants accept `Z` or numeric offset and normalise to UTC; zone-less is read as UTC; unparseable is `ERR_VALIDATION` — `store.py:70-83`
- §2.9 preamble — insert — unrouted path → `ERR_VALIDATION` 404, undeclared method → `ERR_VALIDATION` 405, both before authentication and even with no headers (the only non-400 uses of `ERR_VALIDATION`); trailing slashes tolerated — `app.py:19,29-42`
- §2.9 position 6 — insert — strict typing: integer fields reject `2.0`; bool/number cross-rejection; strings non-empty after trimming but stored verbatim; explicit `null` ≡ absent; absent/empty body ≡ `{}`; non-object body → 400 — `validation.py:9-19,26-34,62-63,85`
- §3.3 — insert — the three sub-scores persist and are readable on the item row; all four fields overwritten at receiving — `serializers.py:386-389`
- §3.3 — insert — a null-priced component contributes 0 to the bundle sum; an ungraded component is skipped by the roll-up and the parent keeps its existing grade when no component carries one — `services.py:244-257`, `calc.py:152-166`
- §3.6 — insert — `clearance_relocation_pending` is set true only by a failed selector run and false only by a successful one; never cleared by a later price rise or by already sitting in a `CLEARANCE` zone, so it can stand true indefinitely — `services.py:213-241`

Pass A also recorded the behaviours it found already uniquely pinned (all `calc.py` constants and formulas; `store.py` clock/ISO/day arithmetic/version semantics; all three envelope shapes and 201-on-create; every serialized field of all 15 entities; `services.py` occupancy set, `zone_remaining_sqft`, `lot_ready`, `days_on_floor`, `unsold_trigger_day_effective`, `mint_entry` cascade; the whole error catalogue) so later passes would not redo them.

### Pass B — `routes/standing.py`, `routes/schedules.py`, `routes/items.py`

491 lines/117,101 chars → 491 lines/121,620 chars; diff vs FINALIZED 24 → 101 lines. Pass A survival verified by grepping five distinctive phrases. **9 ambiguity-pins, 5 mismatch-revisions.**

- §3.1 — insert — ambiguity — email-collision test is exact, case-sensitive equality on the value as submitted, scoped to consignors only (never compared against buyers) — `routes/standing.py:34-36, 171-173`
- §3.1 — insert — ambiguity — all four correctable address fields optional; `display_name`/`email` silently ignored; a body omitting all four or repeating stored values answers 200 with `version`/`updated_at` untouched — `routes/standing.py:89-107`
- §3.1 — insert — ambiguity — retirement gates agreements only: a further markdown step may still be appended to a `RETIRED` schedule — `routes/schedules.py:58-100`
- §3.2 — revise — mismatch — named the two previously unnamed activation refusals: `ERR_CONSIGNOR_SUSPENDED` for a non-ACTIVE consignor, `ERR_SCHEDULE_RETIRED` for a schedule retired **or carrying no steps**; gate order DRAFT → consignor → schedule; `escheat_state` not consulted — `routes/schedules.py:205-214`
- §2.9 ladder 12 — revise — mismatch — added agreement activation to the `ERR_CONSIGNOR_SUSPENDED` endpoint list, with the endpoint-local DRAFT check first — `routes/schedules.py:205-209`
- §3.3 — insert — ambiguity — sub-scores are numbers, not integers: 7.5 accepted; bounds inclusive — `routes/items.py:180-182`
- §3.3 — insert — ambiguity — `condition_grade`, `list_price_cents`, `current_price_cents` also stay null on a screen-rejected piece — `routes/items.py:197-198`
- §3.3 — insert — ambiguity — at screening a parent with components takes the bundle price into `list_price_cents`, `provisional_list_price_cents` and `current_price_cents`; `provisional_condition_grade` keeps its own photo grade while `condition_grade` takes the roll-up; screening a component does not cascade upward — `routes/items.py:205-208`
- §3.5 — insert — ambiguity — all three receiving sub-scores mandatory → `ERR_VALIDATION`, not `ERR_PHOTOS_INSUFFICIENT`; `photo_count` not re-examined — `routes/items.py:225-227`
- §3.5 — revise — mismatch — a lot parent's `list_price_cents`/`condition_grade` are overridden by the bundle calculation, not the grade-and-category figure its own sub-scores produced — `routes/items.py:243-245`
- §3.5 — revise — mismatch — downgrade distance is measured against the grade actually stored in `condition_grade`, i.e. the rolled-up grade for a lot parent — `routes/items.py:247-249`
- §3.6 — insert — ambiguity — a re-placement prices against already-accumulated tenure (no reset to the sequence-1 step) and still enters `ON_FLOOR`, not `MARKED_DOWN` — `routes/items.py:314-319`
- §3.9 — revise — mismatch — recovery unwinds the *most recent* `SHRINKAGE_CREDIT`; a 0-cent or absent credit mints nothing; no zone regains footage because `placement_zone_id` is already null — `routes/items.py:405-430`
- §3.9 — insert — ambiguity — a piece with null `current_price_cents` credits 0 cents and the zero-value `SHRINKAGE_CREDIT` is still minted — `routes/items.py:451-463`
- §2.10 — revise — mismatch — recovery alone restores no footage; a written-off piece consumes square feet again only once re-placed — `routes/items.py:413-415`

### Pass C — `routes/logistics.py`, `routes/commerce.py`, `routes/audits.py`, `routes/ops.py`

491 lines/121,620 chars → 491 lines/125,971 chars; diff vs FINALIZED 101 → 163 lines (40 changed lines, 28 identical headings). Pass A and Pass B phrases verified intact; document still ends on the `ERR_DUPLICATE_EMAIL` row. **10 ambiguity-pins, 7 mismatch-revisions.**

- §2.9 ladder 9 — revise — mismatch — added pickup-job creation to the `ERR_ITEM_STATE_INVALID` list, applied per `item_ids` entry in submitted order — `routes/logistics.py:205`
- §2.9 ladder 10 — revise — mismatch — added sale reversal and delivery-outcome recording, noting both invert the ladder by testing position 15 first — `routes/commerce.py:140-144, 261-269`
- §2.9 endpoint-local paragraph — revise — mismatch — the claim that endpoint-local positions are unobservable is false for pickup-job attachment, where the `SCHEDULED` test precedes positions 9, 27 and 33 — `routes/logistics.py:290-300`
- §3.4 — insert — ambiguity — a listed piece in the wrong state refuses the whole job creation with `ERR_ITEM_STATE_INVALID` (nothing created or moved); no truck-capacity or grade test at creation — `routes/logistics.py:200-207`
- §3.4 — insert — ambiguity — an empty job answers the same `ERR_PICKUP_JOB_STATE_INVALID` (right after the status test); the three actuals persist in the FAILED branch too — `routes/logistics.py:315-337`
- §3.8 — insert — ambiguity — reversal custody failure carries `ERR_ITEM_CUSTODY_INVALID`, and the sale-status test wins for a settled sale — `routes/commerce.py:140-144`
- §3.8 — insert — ambiguity — nothing bars a second delivery order against the same still-`COMPLETED` sale — `routes/commerce.py:192-199`
- §3.8 — revise — mismatch — at outcome recording sale status is tested before order status and **both** refusals are `ERR_SALE_ALREADY_REVERSED` (no delivery-order state error exists) — `routes/commerce.py:260-264`
- §3.8 — insert — ambiguity — the `DELIVERED` custody test refuses with `ERR_ITEM_CUSTODY_INVALID` and runs only after the fork, so `REFUSED` ignores custody — `routes/commerce.py:267-269`
- §3.8 — insert — ambiguity — the cascaded reversal on a refused delivery stamps the sale's `reversed_at` — `routes/commerce.py:287`
- §3.8 — insert — ambiguity — `description` is mandatory on resubmission even when withdrawing (then discarded); the endpoint is not ownership-scoped to the purchaser — `routes/commerce.py:395-411`
- §3.8 — insert — ambiguity — `fault_party` and `adjudicated_by_user_id` are recorded on a denial too, overwriting the filed `fault_party` — `routes/commerce.py:434-440`
- §3.9 — insert — ambiguity — `counted_item_ids` is mandatory but may be empty — `routes/audits.py:194`
- §3.9 — revise — mismatch — abandonment of the prior `COUNTED` audit runs on every fresh count, including a variance-0 one that opens `RECONCILED` — `routes/audits.py:236-253`
- §3.9 — insert — ambiguity — no per-piece re-examination at write-off approval: a piece recovered to `IN_CUSTODY` after the count is written off anyway; an unpriced piece credits 0 and still mints — `routes/audits.py:268-290`
- §3.9 — insert — ambiguity — a `DORMANT` consignor whose balance falls to ≤0 returns to `NONE`; an `ESCHEATED` consignor is skipped by every later run — `routes/ops.py:117-126`
- §4 intro — insert — ambiguity — multi-row writes return only the addressed row (`PickupJob` / `Sale` / `DeliveryOrder` / `DamageClaim` / `ShrinkageAudit`) — `routes/logistics.py:307`, `routes/commerce.py:156,292`, `routes/audits.py:301`

### Orchestrator final verification

- `PRD.md` 489 lines/111,018 chars → `PRD_FINALIZED.md` 489/112,070 → `PRD_COMPLETED.md` 491/125,971. `md5sum` confirms PRD_COMPLETED.md is **not** byte-identical to PRD_FINALIZED.md (163 diff lines, +13,901 chars) — the scan genuinely ran in all three passes.
- Heading count unchanged at 28 — no new sections were added by any pass.
- `PRD_COMPLETED.md` ends on the final `ERR_DUPLICATE_EMAIL | 409` row of the §5 error table — not truncated.
- Final test state re-read directly from disk: all 8 `results.$i.json` report `passed=125, total=125`. Steps 8 and 9 touched only PRD documents, never `implementation/` or the tests, so the clean sweep still stands.

**Pipeline complete.**
