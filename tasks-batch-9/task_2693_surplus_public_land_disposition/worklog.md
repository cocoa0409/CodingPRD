## Step 1: Create task directory — 2026-09-04

Created /home/ubuntu/github/CodingPRD/tasks/task_2693_surplus_public_land_disposition and its workspace/ subdirectory (pre-assigned path from the orchestration prompt; no index auto-allocation performed).

## Step 2: Generate scaffold — 2026-09-04T09:22:00.000Z

All three scaffold artifacts are complete, parse as valid YAML, and lint clean.

## Files (`/home/ubuntu/github/CodingPRD/tasks/task_2693_surplus_public_land_disposition/`)

| file | lines | bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 3961 | 200326 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2472 | 160760 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 2784 | 186649 |

Top-level keys verified: `SCAFFOLD.yaml` contains **no** `scaffold_difficulty_design` / `scaffold_corner_design` key; the other two each contain exactly their single top-level key.

## SCAFFOLD.yaml (§1.0–§1.7)
`difficulty_level: beyond_expert`, `api_prefix: "/"`, `consistency_model: immediate`, `role_model: segregation_of_duties`, `entity_topology: graph`, `state_machine_shape: cyclic`, `primary_archetype: compliance_audit`, `secondary_archetype: multi_party_negotiation`, `complexity_layers: [cascading_side_effects, dual_variant_calculation, optimistic_concurrency, selector_policy]`.

- **17 entities**: Agency, Parcel, SurplusDeclaration, StatutoryNotice, PreferenceOffer, NegotiationRound, Appraiser, Appraisal, AppraisalChallenge, EnvironmentalReview, TitleCurativeItem, DispositionOffering, Bidder, Bid, Conveyance, Fund, ProceedsAllocation
- **10 state machines** (2 with parallel dimensions: PreferenceOffer, Bid; 3 cyclic: Appraisal, EnvironmentalReview, DispositionOffering rescission loop), **2 concurrency rules**, **14 calculations** (incl. `minimum_price_determination` with MARKET_FLOOR vs AFFORDABLE_HOUSING_PREFERENCE variants, `proceeds_waterfall_allocation`, `good_faith_compliance_score` INTERIM/FINAL variants), **76 validations** (priority-ordered), **80 endpoints**, **88 errors**, **8 roles**

## SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)
All **9 rule_ids × 2 differentiated instances = 18**: `dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade` (incl. a 4-link close-bidding failure cascade), `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap` (closed-interval appraiser engagements vs half-open offering windows), `compensating_invariant` (deposit escrow ledger; fund-credit reversal on revert).

## SCAFFOLD_CORNER_DESIGN.yaml (§1.9)
All **9 guide sections, 54 instances (46 with full `test_recipe`, 8 `excluded_because` stubs)**:

| section | instances | full / stub |
|---|---|---|
| entities | 10 | 10 / 0 |
| state_machines | 9 | 7 / 2 |
| calculations | 5 | 3 / 2 |
| validations | 7 | 5 / 2 |
| endpoints | 5 | 5 / 0 |
| errors | 4 | 4 / 0 |
| rbac | 6 | 6 / 0 |
| cross_cutting_complexity_layers | 6 | 4 / 2 |
| consistency_model | 2 | 2 / 0 |

Every instance name is unique across the union of both design files (0 duplicates over 72 names), and all 8 `excluded_because.difficulty_instance` references resolve to real §1.8 instance names. Every `claim_type` is a row of `references/claim-extraction-guide.md` (the rbac `exclusive_operations` label comes from the guide's Table 7 bullet, noted in the file header).

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2693_surplus_public_land_disposition/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2693_surplus_public_land_disposition/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2693_surplus_public_land_disposition/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    80
  §1.1 entities declared:     17
  §1.8 instances scanned:     18
  §1.9 instances scanned:     46
  Calls scanned (§1.8+§1.9):  929

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Two SCAFFOLD.yaml self-consistency fixes made while writing the design files
1. `TitleCurativeItem.actual_cure_cost_cents` description contradicted `minimum_price_determination.formula` (said it was *not* used by minimum-price setting while the formula deducts CURED rows) — description corrected.
2. Validation priority 31 applied the "responder must be a preference entity" requirement to every `POST /notices/{id}/respond`, which would have made a plain `DECLINE` from a non-preference agency illegal — rewritten to be conditional on `EXPRESS_INTEREST`.

No sibling task directory under `tasks/` was read, listed, or grepped.

## Step 3: Copy shared files — 2026-09-04T09:23:00.000Z

Copied ./INSTRUCTION.md to tasks/task_2693_surplus_public_land_disposition/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-04T09:42:00.000Z

PRD generation is complete.

**Output:** `workspace/PRD.md` — **534 lines, 124,173 bytes**, built incrementally (1 `Write` + 8 heredoc appends + 3 small `Edit` patches). File ends at a real boundary: the final row of the §5 error table (`ERR_NO_QUALIFYING_BID | 422`). No content was truncated.

**Structure:** §1 Introduction (3 paras) · §2 with 11 subsections (2.1 RBAC, 2.2 API Response Structure, 2.3 Pagination, 2.4 Record Identity/Versions, 2.5 Logical Clock & Day Arithmetic, 2.6 Whole-Cent Money, 2.7 OCC, 2.8 Segregation of Duties, 2.9 Path Resolution, 2.10 Rejection Precedence, 2.11 Cascade Discipline) · §3 with 11 workflow subsections · §4 endpoint table · §5 error table.

**Verification results**

- **Endpoint coverage: 80/80.** Every scaffold path appears backticked in PRD.md; §4 table has exactly 82 pipe rows (header + separator + 80 endpoints) and exactly 4 columns on every row.
- **Contract 1 (Field-Name Coverage): PASS.** All **177** required identifiers appear verbatim in backticks. Three late gaps (`current_utc`, `offer_id`, `resolution`) were found by the check and fixed in prose.
- **Contract 2 (Rule Coverage): PASS.** All 76 validations with priority orderings, all 88 error ids, both OCC rules, all 14 calculations with full constants, all state machines including parallel dimensions and the cyclic compliance loop, and all multi-link cascades (no-qualifying-bid 4-link, withdrawal 3-link, record 5-effect, reverter 4-link, challenge-denial 3-link).
- **Contract 3 (§3 Path Purity): PASS.** 0 path-like tokens, 0 bare HTTP methods in §3.
- **§2.2 byte-identical** to the doc-generator's canonical section file.
- **§5 catalogue: 88/88** error rows.
- **No meta-text leak:** no "difficulty", "beyond_expert", "harder than expert", "scaffold", "test_recipe", "worked example"; no fuzzy words.
- **Isolation honored:** neither design YAML was opened, grepped, or referenced.

**One incident worth flagging:** a stale `/tmp/err_table.md` left by a *different* task (traffic-signal domain) got appended when the §5 generator script failed on a wrong YAML key (`http_status` vs `http`). Detected immediately, PRD.md truncated back to line 445, regenerated from `SCAFFOLD.yaml` using a task-scoped temp filename. Confirmed clean.

**Scaffold inconsistencies resolved by deliberate choice** (documented so downstream steps stay consistent): duplicate conveyance → `ERR_CONVEYANCE_ALREADY_EXISTS`; determining a non-`SUBMITTED` challenge → `ERR_INVALID_CHALLENGE_STATE`; `response_window_days` out of 60..90 → `ERR_NOTICE_WINDOW_INVALID`; `bid_close_at` not after `bid_open_at` → `ERR_OFFERING_WINDOW_INVALID` (422, per validation 59); declaration create on a non-`AGENCY_OWNED` parcel → `ERR_INVALID_REQUEST` (400); `revaluation_required` set true by both a `SUSTAINED` challenge and the unsuccessful-disposition cascade. Also noted in the PRD: `timely_response_count` counts *preference-entity* timely rounds while the good-faith score's timeliness component counts *custodian-agency* ones — the scaffold defines both that way, so the divergence is called out to stop an implementer conflating them.

**Orchestrator verification:** independently confirmed 534 lines, tail ends at the final §5 error-table row (real section boundary, not mid-sentence), 6 top-level sections present, and the only match for the contamination/meta grep is the word "intersects/intersection" used legitimately in appraiser-engagement interval prose (line 178). PRD accepted without regeneration.

## Step 5: Generate unit tests — 2026-09-04T11:35:00.000Z

Suite is complete. Final state:

## Output directories (task root, not workspace/)

`test_helpers/` — Stage 1:

| file | lines |
|---|---|
| `__init__.py` | 205 |
| `api_client.py` | 593 |
| `api_errors.py` | 217 |
| `assertions.py` | 477 |
| `constants.py` | 197 |
| `factories.py` | 551 |
| `fixtures.py` | 1203 |
| `test_users.py` | 123 |
| `types.py` | 524 |

`test_suite/`:

| file | lines | tests |
|---|---|---|
| `conftest.py` | 86 | — |
| `test_01_minimum_price_and_good_faith_scoring.py` | 191 | 5 |
| `test_02_net_proceeds_and_waterfall.py` | 288 | 6 |
| `test_03_parallel_and_cyclic_state_machines.py` | 352 | 5 |
| `test_04_disposition_cascades.py` | 282 | 5 |
| `test_05_precedence_and_boundaries.py` | 517 | 10 |
| `test_06_cross_entity_state_dependencies.py` | 327 | 6 |
| `test_07_temporal_overlap_windows.py` | 321 | 6 |
| `test_08_compensating_invariants.py` | 403 | 6 |
| `test_09_entity_crud_and_shapes.py` | 506 | 10 |
| `test_10_declaration_and_review_state_machines.py` | 408 | 7 |
| `test_11_derived_calculations.py` | 431 | 5 |
| `test_12_input_validation_rules.py` | 379 | 5 |
| `test_13_endpoint_behaviour.py` | 436 | 5 |
| `test_14_error_conditions_and_concurrency.py` | 741 | 8 |
| `test_15_authorization_rules.py` | 414 | 6 |

**95 tests** across 15 files (min 5 per file), all collected cleanly by `pytest --collect-only` (0.67s, no import errors); pyflakes reports no undefined names.

## Coverage against the two design indices

- **Queue A (§1.8 Difficulty):** 18 non-stub instances, **18 translated, 0 skipped**, 0 stubs in that index.
- **Queue B (§1.9 Corner):** 54 instances total, of which 8 are stubs already excluded by the index itself (they carry `excluded_because` and no `test_recipe`) → 46 non-stub, **46 translated, 0 skipped**.
- **No instance failed the PRD-first two-condition filter**, so there is nothing skipped for lack of verbatim PRD coverage. The 8 index-side stubs (not generator skips) are: `state_machines/corner_preference_offer_parallel_dimensions_advance_independently`, `state_machines/corner_appraisal_cyclic_revision_loop_repeats`, `calculations/corner_proceeds_waterfall_allocation_shares_and_residual`, `calculations/corner_minimum_price_variant_divergence`, `validations/corner_temporal_outranks_fiscal_on_a_late_underbid`, `validations/corner_safety_outranks_constraint_on_appraisal_order`, `cross_cutting_complexity_layers/corner_cascading_side_effects_on_failed_disposition`, `cross_cutting_complexity_layers/corner_dual_variant_good_faith_scoring` — each deduplicates a §1.8 instance already covered in queue A.

## Audits run

- **Design tags:** every one of the 95 tests carries **exactly one** `Design:` line, it is the last non-blank line of the docstring, and all 95 tags resolve to a real non-stub instance in one of the two indices. 0 problems.
- **Citations:** ast-based verbatim checker (docstring quotes only, whitespace-normalised against `workspace/PRD.md`) reports `checked 15 files; missing: 0`.
- **No scaffold leakage:** grep for `scaffold`, `§1.`, `SCAFFOLD.yaml`, `difficulty_design`, `corner_design` across both output dirs returns nothing.

## Notes worth relaying

- Where a recipe's precomputed literal contradicted the PRD, the PRD won: `required_deposit_cents` floor is 5,000,000 (recipes said 4,987,500); appraisal `method` is `INCOME`, not `INCOME_CAPITALIZATION`; `reoffer_count` is 0 immediately after a failed sale and only rises to 1 on the successful re-offer; the failure cascade does not clear `authorized_disposition_type`, so that recipe assertion was dropped.
- Nothing under `workspace/implementation/` was created, read, or modified. No process was killed and no server was started.

**Orchestrator verification:** `test_helpers/` and `test_suite/` are both at the task root; `find workspace -maxdepth 2 -type d -name "test_*"` returns nothing, so the known "test dirs land under workspace/" failure did not occur. 95 `def test_` functions confirmed independently.

## Step 6: Generate implementation — 2026-09-04T11:36:00.000Z

Implementation complete and verified.

## Files (all under `workspace/implementation/`)

| file | lines |
|---|---|
| `start.sh` | 10 |
| `requirements.txt` | 1 |
| `app.py` | 75 |
| `clockmod.py` | 67 |
| `db.py` | 98 |
| `errors.py` | 115 |
| `listing.py` | 19 |
| `lookup.py` | 36 |
| `middleware.py` | 58 |
| `response.py` | 83 |
| `shape.py` | 223 |
| `services/money.py` | 14 |
| `services/derive.py` | 434 |
| `services/calc.py` | 332 |
| `services/waterfall.py` | 105 |
| `services/cascade.py` | 128 |
| `routes/registries.py` | 276 |
| `routes/parcels.py` | 170 |
| `routes/appraisals.py` | 293 |
| `routes/declarations.py` | 271 |
| `routes/notices.py` | 110 |
| `routes/offers.py` | 224 |
| `routes/env_reviews.py` | 147 |
| `routes/offerings.py` | 391 |
| `routes/conveyances.py` | 281 |
| `routes/allocations.py` | 73 |
| **total** | **4034** |

`__pycache__` dirs removed; nothing else on disk. Storage is Python dicts in `db.py` only, `db.reset()` runs in `create_app()`, and a fresh boot returns `total_count: 0` for every registry — no seeding anywhere.

## Coverage
- **Endpoints: 80/80** (enumerated from `app.url_map`, matches the PRD §4 table one-for-one).
- **88 errors / 76 priority-ordered validations**: check order follows the SCAFFOLD numbered `validations` list (auth → shape → existence → uniqueness → OCC → state → temporal → business → constraint → fiscal), which governs where the §3 narrative disagrees. Two such conflicts resolved in favour of the priority list: `ERR_CIRCULATION_TOO_SHORT` (56) before `ERR_RECIRCULATION_BUFFER_VIOLATION` (57) on recirculate, and `ERR_GOOD_FAITH_ROUNDS_NOT_MET` (35) before `ERR_AGREED_PRICE_BELOW_MINIMUM` (68) on conclude.
- **14 calculations**: minimum price (both variants), required deposits, notice/negotiation deadlines, appraisal expiry, good-faith score (interim capped at 75 vs. final with concession points and impasse penalty), award ranking, provisional net / 15% recovery cap / net proceeds, the three-pass proceeds waterfall with signed residual, bidder escrow ledger, and all derived counters.

## Two spec conflicts found (PRD followed, deliberately)
- SCAFFOLD's rescind state machine nulls `awarded_by_user_id`, but PRD §2.8/§3.8 requires comparing it for `ERR_SEGREGATION_OF_DUTIES` on re-award. Retained it — verified re-award by the same clerk is 403 and by a different clerk succeeds.
- SCAFFOLD's withdrawal cascade cancels `AWARDED` offerings with the literal `'declaration withdrawn'`; PRD §3.11 restricts it to `DRAFT/OPEN/EVALUATION` and stores the declaration's own `withdrawn_reason`. Followed the PRD.

Two genuine gaps found and fixed during smoke testing (`routes/offerings.py`): `disqualification_reason` is now set to `'bidder debarred'` at close-bidding grading, and rescind-award now stores the `cancellation_reason` on the ex-WINNING bid and clears `award_rank` on both the ex-WINNING and the restored BACKUP bids.

## Smoke test (5 scripted runs on `PORT=18693`, plus a final fresh boot on 18694; only those PIDs killed, never a broad kill)
Full happy paths exercised end to end:
- **Competitive**: parcel → title items → appraisal → declaration → notices → env review → authorize → offering → 2 sealed bids → close-bidding → award → rescind → re-award to the backup → conveyance → clear-title → record → waterfall.
- **Negotiated/AH preference**: challenge filed and DENIED (deposit forfeited to a fund as `CHALLENGE_FORFEITURE`), appraisal accepted, interest expressed, 6 negotiation rounds, window closed, AGREED at the floor, good faith `SATISFIED` with `final_good_faith_score` 100 (interim 75), `EXEMPT` env review, `NEGOTIATED_SALE` authorized, offering priced `AFFORDABLE_HOUSING_PREFERENCE` at 129,750,000, awarded, recorded, then violation → cure-deadline boundaries → revert.
- **Unsuccessful cascade**: no qualifying bid → offering `FAILED_NO_QUALIFYING_BID`, declaration `UNSUCCESSFUL` with `reoffer_eligible_at` = clock+30d, appraisal `SUPERSEDED`, parcel `STALE`; cooling-off refused then re-offer issued notice round 2.

Numeric invariants confirmed exactly: minimum price 200,000,000 × 0.65 − 250,000 cured = 129,750,000; recoverable curative 250,000 (under the 19,425,000 cap) → net 129,000,000; allocations `FIXED_RESERVE 250,000` + `PERCENTAGE 128,750,000` = 129,000,000 = `net_proceeds_cents`; after revert both funds show `balance 0`-net with `lifetime_credits` intact and `lifetime_debits` = 129,000,000, `allocated_proceeds_cents` back to 0; bidder ledger round-trips (`available + escrow == lifetime_deposits`) and `lifetime_deposits_cents` never moves on internal transfers. Interval boundaries verified in both directions (half-open bidding window admits adjacency, closed circulation window rejects a shared endpoint, cure deadline reverts only strictly after). Error envelopes verified for 401/403/404/409/412/422 including `ERR_IDENTITY_NOT_RESOLVABLE`, `ERR_NOT_RESOURCE_OWNER`, `ERR_STALE_DECLARATION_VERSION`, and `ERR_INVALID_REQUEST` on `limit=101`. No tracebacks in any run.

## Step 7: Test + fix iteration — 2026-09-04

Two iterations of the 8-round parallel stability sweep (`--isolation per-test-server`, 95 tests/round).

| iteration | per-round result | union failing |
|---|---|---|
| 1 | 77/95 in all 8 rounds | 18 (all 8/8 — fully deterministic, no flakiness) |
| 2 | **95/95 in all 8 rounds** | 0 |

No test deleted, no assertion weakened, no `skip`/`xfail`, no `validate_error_is_one_of` relaxation. Test count unchanged at 95.

### Root causes (3 clusters behind the 18 failures)

**A — wire format of server-written instants (14 tests). Test bug.**
`test_helpers/assertions.py::format_instant` rendered `%Y-%m-%dT%H:%M:%SZ`, and 25 assertions in `test_suite/` compared server-stamped timestamps against no-fraction literals. PRD §2.4 fixes the format: "`created_at` is the ISO 8601 UTC instant, **with three fractional digits**" (§2.2 the same for `api_request_timestamp`), and §2.5 groups every server-written stamp with it. The implementation's `clockmod.fmt` was already correct and uniform. Fixed the helper plus the 25 literals.

Only fields the server *computes* were changed (`expires_on`, `reported_at`, `adopted_at`, `certified_at`, `responded_at`, `notice_issued_at`, `response_deadline_at`, `notice_response_deadline_at`, `negotiation_opened_at`, `negotiation_deadline_at`, `reoffer_eligible_at`, `cure_deadline_at`, `reverted_at`, `reversed_at`). The 9 comparisons against *client-supplied* dates (`engagement_start_on`/`_end_on`, `circulation_start_on`/`_end_on`, `bid_open_at`, `license_expires_on`) were left alone — the implementation echoes those verbatim via `db.set_raw`, which the PRD does not forbid.

**B — `easement_area_sqft` typing (2 tests). Implementation bug.**
`routes/parcels.py::resolve_title_item` used `shape.req_int(..., 1)`. PRD §3.2 constrains the area only to be "supplied with an area strictly greater than zero"; the integer discipline of §2.6/§2.10 is scoped to `_cents` fields. Switched to the existing `shape.req_positive_number` (already used for `acreage`). Zero, negative and omitted areas are still `ERR_INVALID_REQUEST`.

**C — notice-response check order (1 test). Implementation bug.**
`routes/notices.py::respond_to_notice` ran the `claimed_preference_category`-equals-agency-category comparison before the preference-right gate, so a non-preference recipient got `ERR_INVALID_REQUEST` instead of `ERR_NOT_PREFERENCE_ENTITY`. PRD §3.5 orders these explicitly — the preference gate first, and then "It **further** requires `claimed_preference_category` … to equal the recipient agency's own". The mismatch test reads a stored entity's field, so it is not in §2.10's shape layer (which covers only presence, enum membership, `_cents`, date parseability and declared ranges). Presence/enum validation stayed in the shape layer; only the cross-entity comparison moved below the gate. A genuine preference entity supplying a mismatched claim still gets `ERR_INVALID_REQUEST`.

## Step 7: Run tests and iterate — 2026-09-04T12:05:00.000Z

Done. Exiting on a clean 8-round parallel sweep.

## Summary

**Iterations run: 2**

| iteration | per-round | union failing |
|---|---|---|
| 1 | 77/95 in all 8 rounds | 18 (every one failing 8/8 — fully deterministic, zero flakiness) |
| 2 | **95/95 in all 8 rounds** (0 failed, 0 errors) | 0 |

**Tests deleted: none.** Every failing test passed STEP 1a (verbatim PRD coverage) and STEP 1b (unique derivability), so none met the deletion criterion. No assertion was weakened — no `skip`/`xfail`, no `error_id`→HTTP-status downgrade, no `validate_error_is_one_of` relaxation. Test count unchanged at 95.

### Fixes applied to `test_helpers/`
- **`test_helpers/assertions.py` → `format_instant`** — rendered `%Y-%m-%dT%H:%M:%SZ` while its own docstring claimed to render "the way the API writes them". PRD §2.4 fixes the format as "the ISO 8601 UTC instant, **with three fractional digits**" (§2.2 likewise for `api_request_timestamp`). This also repaired the derived `add_days` / `expected_expires_on` helpers.

### Fixes applied to `test_suite/` (assertion mis-translation, same root cause)
- **25 literals across 10 files** compared server-stamped timestamps against no-fraction strings (`…T00:00:00Z` vs the correct `…T00:00:00.000Z`). This one bug accounted for 14 of the 18 failures.
- Scoped deliberately: only fields the server *computes* were changed. The 9 comparisons against *client-supplied* dates (`engagement_start_on`/`_end_on`, `circulation_start_on`/`_end_on`, `bid_open_at`, `license_expires_on`) were left untouched — the implementation echoes those back verbatim via `db.set_raw`, which the PRD nowhere forbids, and those assertions were already passing.

### Fixes applied to `implementation/`
- **`routes/parcels.py` → `resolve_title_item`** — used `shape.req_int(easement_area_sqft, 1)`, an integer-only restriction that traces to no PRD sentence. §3.2 requires only that the area be "supplied with an area strictly greater than zero", and §2.6/§2.10 scope the integer discipline to `_cents` fields. Switched to the pre-existing `shape.req_positive_number` (already used for `acreage`). Verified zero, negative and omitted areas are still `ERR_INVALID_REQUEST`.
- **`routes/notices.py` → `respond_to_notice`** — ran the `claimed_preference_category`-equals-agency-category comparison ahead of the preference-right gate, so a non-preference recipient received `ERR_INVALID_REQUEST` rather than `ERR_NOT_PREFERENCE_ENTITY`. §3.5 orders these explicitly: the gate first, then "It **further** requires…". The mismatch test reads a *stored entity's* field, so it cannot sit in §2.10's shape layer (presence, enum membership, `_cents`, date parseability, declared ranges). Presence/enum validation stayed in the shape layer; only the cross-entity comparison moved below the gate.

### Notable finding
The failure profile was unusually clean — all 18 failures reproduced identically in all 8 rounds, so no time was lost to load-induced false positives, and 14 of them collapsed to a single format bug in one helper function. Both implementation fixes were **removals of over-strict/mis-ordered checks not traceable to PRD prose**, not additions of behaviour; each was smoke-tested on a private port (21693, killed by its own PID) to confirm the PRD-required checks they sit next to still fire — notably that a genuine preference entity supplying a mismatched claim still gets `ERR_INVALID_REQUEST`. Storage remains in-memory dicts with no seeding.

**Orchestrator verification:** independently parsed all 8 `results.$i.json` files from the final sweep — every round reports `passed == total == 95`. Step 8 is NOT skipped (2 `implementation/` fixes, 1 `test_helpers/` fix, 25 `test_suite/` literal fixes).

## Step 8: Finalize PRD — 2026-09-04T12:12:00.000Z

Done. `PRD_FINALIZED.md` created as a 3-line patch of `PRD.md`.

## Line counts
- `PRD.md`: 534 lines / 124,173 bytes
- `PRD_FINALIZED.md`: 534 lines / 126,044 bytes
- Delta: **0.0%** by line (3 lines revised in place, no lines added/removed), **+1.5%** by byte

## Changes
- **§2.5 (Logical Clock)** — revise — pinned the wire format of instants: every instant the service produces itself (`created_at`/`updated_at`, the listed stamps, and the computed deadline/expiry instants `response_deadline_at`, `notice_response_deadline_at`, `negotiation_deadline_at`, `expires_on`, `reoffer_eligible_at`, `cure_deadline_at`) renders with three fractional digits (unmoved clock → `2026-08-01T00:00:00.000Z`), while the eight client-supplied instants are stored and echoed back verbatim — `implementation/clockmod.py:40`, `implementation/services/derive.py:18-25` (`_inst`), `implementation/db.py:96` (`set_raw`)
- **§3.2 (Curing Title)** — revise — `easement_area_sqft` is a plain number strictly greater than zero, fractional values well formed, non-numeric values `ERR_INVALID_REQUEST` — `implementation/routes/parcels.py:156`, `implementation/shape.py:req_positive_number`
- **§3.5 (Statutory Notice Round)** — revise — split the `claimed_preference_category` requirement across the §2.10 precedence order: presence + 4-member enum membership are shape checks ahead of notice state and the preference-right gate (and ignored entirely on `DECLINE`); the comparison against the agency's own `preference_category` runs after the `ERR_NOT_PREFERENCE_ENTITY` gate and before the response-deadline check — `implementation/routes/notices.py:64-81`

## Per-edit pre-edit search log

**Edit 1 — subject: wire rendering of every instant-valued field**
(b) Enumerated/read: `clockmod.py` (`fmt`, `stamp`, `DEFAULT_CLOCK`, `parse`), `response.py` (`_meta` → `clockmod.stamp`), `db.py` (`insert`, `insert_event`, `touch`, `set_raw`), `services/derive.py` (`_inst`, `_common`, all 17 serialisers), `grep -rn "set_raw"` (10 sites: `appraisals.py:79,80,132`, `registries.py:128`, `env_reviews.py:71,72,144,145`, `offerings.py:138,139`), `grep -rn "req_instant\|opt_instant"` (11 sites incl. `current_utc`), `grep -rn "bid_close_at\|bid_open_at"` to confirm no server recomputation shadows a raw value, `grep -rn "isoformat\|strftime"` to confirm a single rendering path.
(c) Adjustments: (i) dropped an initial "the stamps just named and the deadlines *computed from them*" phrasing — `expires_on` derives from the client's `effective_date`, not from a stamp — and used "every deadline or expiry instant the service computes"; (ii) added `notice_issued_at`-class stamps into scope by generalising to "every instant-valued field the service produces itself" rather than relying on §2.5's incomplete stamp list; (iii) enumerated the eight client-echoed fields explicitly rather than writing a general "date fields" rule, since `current_utc` is parsed but never echoed.

**Edit 2 — subject: numeric-type validation of a non-`_cents` numeric field**
(b) Enumerated/read: `routes/parcels.py:32` (`acreage`, same validator) and `:145-172` (`resolve_title_item`), `shape.py` (`req_positive_number`, `req_cents/opt_cents`, `req_int/opt_int`, `req_fraction/opt_fraction`), `grep -rn` across `routes/` and `services/` (11 sites: `expected_parcel_version`, `expected_declaration_version`, `amount_cents`, `priority_rank`, `allocation_pct`, `responded_to_round_number`, `reverter_cure_period_days`, `response_window_days`, `acreage`, `easement_area_sqft`), PRD §2.6 / §2.10 / §3.1 prose, `derive.title_item_out` (area echoed as stored).
(c) Adjustments: rejected a §2.6-level sentence of the form "numeric fields not ending in `_cents` may be fractional" — that would have been a false universal against `response_window_days`, `priority_rank`, `reverter_cure_period_days`, `responded_to_round_number` and the two `expected_*_version` fields, all `opt_int`/`req_int`. Scoped the wording to `easement_area_sqft` alone and left §3.1's identically-phrased `acreage` sentence verbatim (same validator, so no contradiction).

**Edit 3 — subject: validation and precedence of `claimed_preference_category` on a notice response**
(b) Enumerated/read: `routes/notices.py:52-113` in full (ownership check, `shape.body`, `req_enum` on `response_type`, `opt_str` on `intended_use`, `req_enum` on `claimed_preference_category` inside the `EXPRESS_INTEREST` branch, then `ISSUED` state → `is_preference_entity` gate → claim comparison → `ERR_NOTICE_RESPONSE_LATE` → the two write branches → preference-offer insert with `preference_category` copied from the claim), `notices.py:19-21` (`OFFER_CATEGORIES` = the 4 members) vs `registries.py:22-23` (`PREFERENCE_CATEGORIES` includes `NONE`), `services/calc.recompute_offer_minimum`, `derive.notice_out`/`offer_out` (claim only ever stored on the interest branch), PRD §2.10 shape/state/temporal/business layering.
(c) Adjustments: (i) wrote the enum clause as "drawn from those four" rather than "the agency's own enum", because an agency may legitimately hold `preference_category` `NONE` while the claim enum excludes it — a `NONE` claim is a shape rejection, not a mismatch; (ii) added the `DECLINE`-ignores-the-field parenthetical after confirming the field is neither validated nor stored on that branch; (iii) stated "before the response-deadline check" only for the comparison, since asserting a fuller re-ordering of §3.5's deadline sentence would have gone beyond what the code shows.

**Orchestrator verification:** `PRD_FINALIZED.md` exists, is 534 lines / 126,044 bytes, and `cmp` confirms it is NOT byte-identical to `PRD.md` (`diff` reports 12 lines across the 3 revised sites). Step 8 genuinely ran.

## Step 9: Complete PRD — 2026-09-04T12:45:00.000Z

Run as **three sequential module-partitioned passes** over one shared `PRD_COMPLETED.md` (pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 edited in place and were explicitly forbidden from copying). Partitioning was an orchestrator decision: a single pass over a 534-line / 126KB PRD against a 4034-line implementation has a known failure mode where the scan silently does not happen and the output comes back byte-identical to its source.

- Pass 1 partition: `app.py`, `clockmod.py`, `db.py`, `errors.py`, `listing.py`, `lookup.py`, `middleware.py`, `response.py`, `shape.py`, all of `services/`
- Pass 2 partition: `routes/registries.py`, `parcels.py`, `appraisals.py`, `declarations.py`, `notices.py`
- Pass 3 partition: `routes/offers.py`, `env_reviews.py`, `offerings.py`, `conveyances.py`, `allocations.py`

### Totals
- `PRD_FINALIZED.md` 534 lines / 126,044 bytes → `PRD_COMPLETED.md` 534 lines / **134,767 bytes** (+8,723 bytes, +6.9%). Line count unchanged: every one of the 32 edits is an in-paragraph insert or revision; no new sections.
- **32 edits: 23 ambiguity-pins, 9 mismatch-revisions.**

### Pass 1 — core + services (7 ambiguity-pins, 2 mismatch-revisions)
- §2.3 Pagination — insert — ambiguity — non-integer `limit`/`offset` is `ERR_INVALID_REQUEST`; filter query params validated the same way (enum membership; boolean accepts only `true`/`false`/`1`/`0` case-insensitive; undeclared params ignored) — `response.py:60-70`, `shape.py:191-219`
- §2.3 ordering — insert — ambiguity — every ordering stabilised by insertion order on ties; row `id` never participates — `db.py:85`, `listing.py:19`, `routes/allocations.py:23-26`
- §2.5 — insert — ambiguity — client-supplied instants normalised to UTC (trailing `Z` and explicit numeric offsets converted, no-offset read as UTC); unparseable is `ERR_INVALID_REQUEST` — `clockmod.py:43-58`
- §2.9 — revise — **mismatch** — the 404 codes never apply to the acting principal: an unresolvable acting `Bidder`/`AgencyRepresentative`/`Appraiser` is `ERR_IDENTITY_NOT_RESOLVABLE` (403), not `ERR_BIDDER_NOT_FOUND`/`ERR_AGENCY_NOT_FOUND` — `middleware.py:47-53`
- §3.7 — insert — ambiguity — concession points are zero when the offer has no custodian-agency round and zero when `ah_minimum_price_cents` is empty — `services/calc.py:159-166`
- §3.7 — insert — ambiguity — with no `ACCEPTED` appraisal the minimum-price rule yields nothing rather than zero; `ah_minimum_price_cents` stays empty until a valuation is accepted — `services/calc.py:64-67`, `:103-108`
- §3.8 — revise — **mismatch** — the circulation-overlap test considers only reviews that recorded an interval; an `EXEMPT` review records none and takes no part — `services/calc.py:230-231`
- §5 intro — insert — ambiguity — unknown path answers `ERR_INVALID_REQUEST` with HTTP 404, unaccepted method HTTP 405, both in the standard envelope — `app.py:44-52`

### Pass 2 — registries/parcels/appraisals/declarations/notices (8 ambiguity-pins, 2 mismatch-revisions)
- §2.10 — revise — **mismatch** — the addressed path resource of an ownership-, engaged-appraiser- or segregation-gated operation is resolved *before* the shape layer, so a bad path id on those endpoints returns its 404 ahead of any body complaint — `appraisals.py:115,251`, `notices.py:54`
- §2.10 — insert — ambiguity — the shape layer additionally requires every string-valued body field to be non-empty — `registries.py:51`, `parcels.py:31`, `appraisals.py:122`
- §3.1 — insert — ambiguity — `contact_email` is required non-empty and never checked for e-mail syntax, on agencies and bidders alike — `registries.py:53,160`
- §3.1 — insert — ambiguity — a PATCH naming none of its amendable fields is accepted and still refreshes `updated_at` and increments `version` — `registries.py:106,275`, `parcels.py:94`
- §3.1 — insert — ambiguity — debarment has no state guard: re-debarring an already-`DEBARRED` bidder is accepted, overwrites `debarment_reason`, bumps `version`; nothing restores `CLEAR` — `registries.py:211`
- §3.3 — insert — ambiguity — ordering an appraisal imposes no precondition on the parcel; readiness is demanded only at authorization and offering creation — `appraisals.py:45`
- §3.4 — revise — ambiguity — the 30-day window is tested *before* standing (temporal outranks statutory rule under §2.10); standing is conferred by being recipient of any notice on any declaration of the appraised parcel, any round, any notice status — `appraisals.py:167,187`
- §3.4 — insert — ambiguity — the §2.8 SoD comparison spans every declaration on the appraised parcel whatever its status — `appraisals.py:254`
- §3.5 — revise — **mismatch** — `WITHDRAWN` is reachable only from `DRAFT` and `OFFERING_AUTHORIZED`, not "from every non-terminal status" — `declarations.py:264`
- §3.5 — insert — ambiguity — `agreed_price_cents`, `remediation_note` and both good-faith score fields start empty; no interim score until the first round — `notices.py:110`
- §3.8 — insert — ambiguity — an explicitly empty `authority_findings` is a shape rejection (`ERR_INVALID_REQUEST`, 400), not `ERR_EXCHANGE_FINDINGS_REQUIRED` (422) — `declarations.py:170`

### Pass 3 — offers/env_reviews/offerings/conveyances/allocations (8 ambiguity-pins, 5 mismatch-revisions)
- §3.5 — revise — **mismatch** — dropped "opening an environmental review" from the `ERR_INVALID_DECLARATION_STATE` list; it carries no declaration-state precondition — `env_reviews.py:36`
- §3.8 — insert — ambiguity — a review may be opened against a declaration in **any** status — `env_reviews.py:26-36`
- §3.8 — insert — ambiguity — an `EXEMPT` review's supplied dates must still parse; for every other class both dates are required and omission is a 400 in the shape layer, ahead of the declaration's 404 — `env_reviews.py:29-35`
- §3.8 — insert — ambiguity — certifying an `EXEMPT` review draws `ERR_INVALID_ENV_REVIEW_STATE` — `env_reviews.py:99-103`
- §3.8 — revise — **mismatch** — recirculation's three window checks reordered to length → buffer → overlap — `env_reviews.py:118-131`
- §3.6 — insert — ambiguity — the representative's owner/party gate reads the raw body ahead of the shape layer, so a missing or non-`PREFERENCE_ENTITY` `party` from a rep is `ERR_NOT_RESOURCE_OWNER`; the ownership half wins when both are offended; an officer may append for either party — `offers.py:71-81`
- §3.6 — insert — ambiguity — `responded_to_round_number` below 1 is a shape-layer 400, not `ERR_INVALID_ROUND_REFERENCE` — `offers.py:89`, `shape.py:89`
- §3.6 — revise — **mismatch** — conclude presents the declaration-state gate before the offer's own `IN_NEGOTIATION` gate; both-offended yields `ERR_INVALID_DECLARATION_STATE` — `offers.py:189-192`
- §2.10 — revise — **mismatch** — carved the two §3.6 preference-offer operations out of the universal "addressed entity's own state before a related entity's state" clause (every other route module does check the addressed row first, so the clause was a false universal) — `offers.py:87,190`
- §3.6 — revise+insert — mismatch + ambiguity — `ERR_GOOD_FAITH_ROUNDS_NOT_MET` is "First" and the price floor "Second"; null `ah_minimum_price_cents` skips the floor entirely; a missing `agreed_price_cents` is a shape-layer 400 ahead of the 404 and both state gates — `offers.py:183-186,203-210`
- §3.8 — insert — ambiguity — a debarment disqualification at close-bidding records `disqualification_reason` as the fixed text `bidder debarred` — `offerings.py:293-295`
- §3.8 — insert — ambiguity — rescission copies `cancellation_reason` onto the winning bid's `disqualification_reason`, clears every ranked bid's `award_rank`, and leaves the offering's own `cancellation_reason` empty on the competitive branch — `offerings.py:369-379`
- §3.8 — revise — **mismatch** — a `counterparty_bidder_id` tendered in place of the required agency leg on a negotiated sale is `ERR_NEGOTIATED_BUYER_REQUIRED` — `offerings.py:113-121`
- §3.10 — insert — ambiguity — `deed_restrictions` entries must each be non-empty and need not be distinct — `conveyances.py:53`, `shape.py:170-180`

### Integrity check (pass 3, re-verified by orchestrator)
- Sections §1–§5 all present; no new sections added.
- §4 endpoint table: 80 endpoint rows intact. §5 error table: 88 rows intact.
- File ends at a real boundary — the final `ERR_NO_QUALIFYING_BID | 422` row of the §5 catalogue.
- `cmp` vs `PRD_FINALIZED.md`: DIFFERENT (60 changed lines across Step 8 + all three passes), so the scan demonstrably ran.
- Orchestrator re-confirmed independently: PRD.md 124,173 B / PRD_FINALIZED.md 126,044 B / PRD_COMPLETED.md 134,767 B, all three distinct, all 534 lines; exactly one `worklog.md` (task root, no cwd-drift strays); 8 passing `results.*.json` retained from the final sweep.

**PIPELINE COMPLETE.** No implementation or test files were modified during Steps 8–9, so the Step 7 green sweep (95/95 × 8 rounds) remains valid.
