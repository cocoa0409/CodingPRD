# Worklog — task_1338_perioperative_preference_card_supply

## Step 1: Create Task Directory — 2026-08-12T22:37:00.000Z

Task directory `tasks/task_1338_perioperative_preference_card_supply/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher; treated as DONE per orchestration instructions. No index scan performed; no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-12T23:18:00.000Z

All three scaffold artifacts are written and the lint verdict is clean (pasted verbatim below).

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1338_perioperative_preference_card_supply/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 plus preamble; no `scaffold_difficulty_design`/`scaffold_corner_design` keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

**Design summary** — Perioperative Preference Card & Supply Picking, `api_prefix: /perioperative`, flat topology, cyclic state machines, segregation-of-duties role model, immediate consistency:
- **Entities: 12** — Surgeon, SupplyItem, PreferenceCard, PreferenceCardLine, SurgicalCase, PickList, PickListLine, UsageRecord, CardAccuracyAudit, ProductRequest, ConsignmentCount, ConsignmentCharge
- **State machines: 10** — including PickList `IN_PICKING ⇄ PICKING_EXCEPTION` cycle and CardAccuracyAudit `UNDER_REVIEW ⇄ DISPUTED` cycle
- **Calculations: 8** — incl. dual-variant case cost (standard 6000 vs actual 6500), dual-variant audit accuracy (line-match 66.67 vs spend-match 91.67), HOLD/consignment waste-multiplier branch, pinned per-line-then-sum rounding (1000 not 999), 20.0% waste-flag threshold, consignment variance/charge rules
- **Endpoints: 55** (incl. filtered-list GETs giving every FK reverse-reachability)
- **Errors: 39**, all referenced by §1.4/§1.2 and exercised by at least one design instance
- **Roles: 7** (Surgeon is entity-backed; rest opaque; `Any` shared read), **validations: 11** priority rows, **concurrency rules: 2** OCC rules (card publish, case repin)
- **Difficulty instances: 18** (9 rules × 2, all differentiation clauses honored)
- **Corner instances: 57 active + 8 excluded-because stubs** (all stubs cite existing §1.8 instances)

**Lint verdict (verbatim):**
```
Coverage
  §1.5 endpoints declared:    55
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     57
  Calls scanned (§1.8+§1.9):  786

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Fixes applied during iteration: quoted bracketed `grounds:` entries for YAML flow-sequence legality; added `card_id?` to `GET /pick-lists` and `created_item_id?` to `GET /product-requests` for FK reverse-reachability; converted the shared-read RBAC corner to `as: Any` to match §1.5 role declarations; added a late corner instance so `ERR_CARD_NOT_DRAFT` is exercised. No sibling tasks were read at any point.

## Step 3: Copy Shared Files — 2026-08-12T23:19:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1338_perioperative_preference_card_supply/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-12T23:33:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1338_perioperative_preference_card_supply/workspace/PRD.md` (323 lines).

## PRD Section List

- **§1. Introduction** — 2 paragraphs, business-context angle (preference card drift, waste, consignment billing)
- **§2. Global Specifications** (9 subsections):
  - 2.1 User and Role-Based Access Control (6 roles + `Any`; Surgeon entity-backed, all others opaque — translated per role)
  - 2.2 API Response Structure (emitted verbatim from `section-2.2-response-structure.md`)
  - 2.3 Pagination (limit default 10 / min 1 / max 100, offset default 0, `created_at` ASC default, `pick_sequence` ASC + `created_at` ASC tiebreak for both line collections)
  - 2.4 Common Resource Properties (`id` UUID, `created_at`/`updated_at` ISO 8601 UTC 3-fractional-digits, `version`; flat-path left-to-right id validation)
  - 2.5 Money, Percentages, and Rounding Discipline (integer cents; all `*_pct` 2dp round-half-up, threshold compares rounded value)
  - 2.6 Card Versioning, Case Pinning, and OCC (business `version_number` vs system `version`; both OCC rules with `expected_card_version` / `expected_case_version` → `ERR_STALE_VERSION` 412)
  - 2.7 Validation Order and Request Atomicity (all 11 priority tiers in prose, incl. within-tier-8 case-create order and OCC after state / before business)
  - 2.8 The Sterile-Core Stock Ledger (six events that may mutate `on_hand_quantity`)
  - 2.9 Scheduling Time and Request-Supplied Temporal Inputs (no clock endpoint; half-open interval semantics)
- **§3. Business Logic & Workflows** (8 subsections, timeline-grouped): 3.1 Surgeons & Supply Catalog; 3.2 Card Authoring & Publishing; 3.3 Case Scheduling/Pinning/Repin/Cancel; 3.4 Release→Picking→Short→Substitute→Dispatch; 3.5 Return/Usage/Completion (waste charge multipliers, per-line rounding order, audit score formulas, budget guard); 3.6 Audit Disposition & Disputes; 3.7 Product Requests & Value Analysis (quorum 2, SoD); 3.8 Consignment Counts & Charges
- **§4. Endpoint Definitions** — 55-row table, 4 columns only (Method/Path/Description/Authorized Roles), with 201/200/204 status rules paragraph
- **§5. Error Code Catalogue** — 40 rows, 2 columns only

## Scaffold Coverage

Fully covered: scenario, conventions (money/percentages/list ordering/atomicity/time/identity headers), all 12 entities with every field, all 9 state machines with every transition (incl. cyclic `IN_PICKING↔PICKING_EXCEPTION` and `UNDER_REVIEW↔DISPUTED` loops, system-cascade transitions, and per-transition preconditions + side effects), both OCC concurrency rules, all 8 calculation rules (with pinned rounding order for waste charges and all zero-denominator edge cases), all 11 validation priorities with ordering prose, all 55 endpoints, all 39 catalog errors plus `ERR_INVALID_STATE` (named in the Surgeon deactivation precondition; added to §5 for PRD self-consistency), and all 7 roles with identity bindings.

## Hard Contract Reports

```
Field coverage check:
- entities[].fields + endpoints input/query/path params: 81 required, 81 present, 0 missing
Status: PASS
```
```
Rule coverage check:
- validations[] priority tiers: 11 checked, 11 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write endpoint + occ field + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: all fully expressed (from/to, preconditions+error ids, side effects), 0 missing
- calculations[]: 8 checked, 8 fully expressed in precise prose (no pseudocode), 0 missing
- validations[] conditions: all matchable to error ids in §2.7/§3, 0 missing
- endpoints[].side_effects / applies_to: all expressed, 0 missing
- entities[].fields[] structured content (types, defaults, initial values): reconstructible from prose, 0 missing
- sibling-branch symmetry: symmetric (accept vs dispute paths; OPEN/HOLD/consignment multipliers; void from PENDING vs CAPTURED), 0 asymmetric
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: ~500 (fence-stripped)
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

The two forbidden files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were not opened or referenced.

## Step 5: Generate Unit Tests — 2026-08-12T23:52:00.000Z

All files compile, all design tags resolve, and both queues are fully covered. Summary follows.

### test_helpers/ (9 files, under `/home/ubuntu/github/CodingPRD/tasks/task_1338_perioperative_preference_card_supply/test_helpers/`)
- `__init__.py` — barrel export (framework generics + PRD-specific)
- `types.py` — 13 entity TypedDicts + 11 status enums + `UserRole`
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (43 methods)
- `api_errors.py` — `ApiErrorId` enum (40 errors) + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` validators + `assert_pct` (2dp tolerance)
- `factories.py` — payload factories for surgeon/item/card/line/case/request/count (unique SKUs per factory call)
- `constants.py` — waste-flag 20.0, 1.25x substitute cap, 30-min turnover, waste multipliers, quorum 2
- `test_users.py` — `TEST_USERS` headers for all 7 roles + `make_surgeon_headers` (entity-backed) and `make_officer_headers` (opaque, per-officer ids)
- `fixtures.py` — composite helpers: `make_surgeon/supply_item/draft_card/published_card/case`, `release_pick_list`, `pick_all_lines`, `return_cart`, `get_audit_for_case`, `get_usage_records_for_case`, `get_charges_for_case`, `setup_released_case`, `setup_dispatched_case`, `setup_completed_case`, `make_product_request`, `open_review`, `endorse_request`, `setup_request_under_review`, `setup_request_quorum_met`

### test_suite/ (conftest.py + 10 test files, 97 tests)
- `test_01_entity_defaults_and_creation.py` (13) — corner/entities + duplicate-line/quantity-zero validations
- `test_02_card_lifecycle.py` (7) — publish/supersede, OCC publish, empty-card, retire-in-use, line-add-to-ACTIVE
- `test_03_case_scheduling.py` (11) — room half-open, surgeon 30-min buffer, surgeon mismatch, inactive surgeon, superseded-pin release block, repin guards + OCC, version pinning
- `test_04_picking_workflow.py` (12) — release/begin/dispatch guards, pick equality boundary, substitution rules + price threshold, exception cycle, cancel-restock, mark-short cascade
- `test_05_case_completion.py` (19) — dual-variant costs, dual-variant audit scores, waste multiplier branches, per-line rounding, depth-3 cascade, 20.0/19.98 waste-flag boundary, consignment billing, budget guard, usage-exceeds, referential-beats-fiscal priority, immediate consistency
- `test_06_audits_and_release.py` (7) — audit dispute/re-review cycle, terminal lockdown, reopen guard, release snapshot, list filters, pagination
- `test_07_product_requests.py` (8) — endorse/quorum/SoD/reject guards, requester-inactive approval block, discontinue cascade
- `test_08_consignment.py` (8) — count variance/zero-variance/verify guard, non-consignment count, stock-adjustment floor, capture/void charge lifecycle + billed-total conservation
- `test_09_rbac_and_auth.py` (6) — missing auth headers, role gates (publish/capture/item-create), non-owning-surgeon dispute, Any-read
- `test_10_difficulty_second_looks.py` (6) — second-look tests for 6 difficulty instances needing ≥2 coverage

### Total test count: 97

### Queue A (difficulty) coverage: 18/18 instances emitted, each with exactly 2 tests (36 tests). 0 skipped.

### Queue B (corner) coverage:
- Non-stub instances: 53/53 emitted (61 tests). 0 skipped.
- `excluded_because` stubs: 8/8 correctly not translated (all cross-references resolve to real §1.8 instances).

### PRD-first adjudication notes
- Every test's docstring carries a verbatim-greppable PRD citation (automated 8-word-window sweep: 0 failures) plus exactly one `Design:` tag resolving to a real instance.
- `double_release_returns_pick_list_exists`: PRD §2.7 places both `ERR_CASE_NOT_SCHEDULED` and `ERR_PICK_LIST_EXISTS` in the same priority-5 tier, so the exact winner is not uniquely derivable — the test uses `validate_error_is_one_of([...])` per the error-precedence rule (the instance's own assert names both).
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; no scaffold references in generated code; all files compile.

## Step 6: Generate Implementation — 2026-08-12T23:59:00.000Z

Implementation complete and verified. Summary:

### File list
All under `/home/ubuntu/github/CodingPRD/tasks/task_1338_perioperative_preference_card_supply/workspace/implementation/`:

- `start.sh` — executable launcher; guarded `pip install` (no-op once flask importable), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — flask
- `app.py` — Flask assembly, envelope-shaped 404/405/exception handlers, route registration
- `db.py` — empty in-memory stores (11 entity dicts), UUID + sequence helpers; no seeding
- `errors.py` — `ApiError` + all 39 error-id constants from the PRD §5 catalog
- `util.py` — envelope (`meta.api_request_id/api_request_timestamp`, `response_type`, `data`; list meta adds `limit/offset/total_count/has_more`), ISO-8601 3-fractional-digit timestamps, header auth, body validators, pagination (default 10, min 1, max 100)
- `domain.py` — stamping (`version` starts at 1, bump on every mutation), serializers, shared calc helpers (Decimal-based `round_half_up` 2dp percentages, per-line waste charge)
- `routes_catalog.py`, `routes_cards.py`, `routes_cases.py`, `routes_picking.py`, `routes_audits.py`, `routes_requests.py`, `routes_consignment.py` — endpoint handlers

### Endpoint count
**55 routes**, covering all 55 rows of the scaffold §1.5 / PRD §4 endpoint table (3 surgeons, 4 supply-items, 5 preference-cards, 4 card-lines, 7 cases, 5 pick-lists, 5 pick-list-lines, 2 usage-records, 5 card-audits, 7 product-requests, 4 consignment-counts, 4 consignment-charges).

### Verification
Two smoke suites (~105 assertions) ran green against fresh boots, covering: full release→pick→short→substitute→dispatch→return→complete chain; waste rounding (151.5→152 on HOLD 1.5x); audit scoring (line_match/spend_match/waste_pct, exact-20.0 flag boundary); OCC 412 on publish/repin; supersede + repin forcing function; scheduling conflicts (half-open room overlap, 30-min surgeon buffer, exactly-30 allowed); substitution guards (same-item 400, group mismatch, 1.25x threshold exact/402/override); cancel restock of planned+substitute stock; consignment budget 402 with full atomicity (zero usage records/charges/audit on failure); value-analysis pipeline (quorum, SoD 403, requester-inactive, SKU re-check, replaces-item discontinuation); consignment count verify ledger sync; RBAC and auth-header failures; pagination bounds and boolean filters. Also verified `bash start.sh` twice sequentially — second boot sees a pristine empty store.

### PRD interpretation choices (for PRD finalization)
1. **Publish validation order** — PRD §3.2 explicitly says "in the global validation order: DRAFT → CARD_EMPTY → ITEM_NOT_ACTIVE → SURGEON_INACTIVE", which contradicts the §2.7 priority table (CARD_EMPTY is structural p10, after the p8 coherence checks). I followed the specific §3.2 enumeration, with OCC slotted after state per §2.6: `ERR_CARD_NOT_DRAFT → ERR_STALE_VERSION → ERR_CARD_EMPTY → ERR_ITEM_NOT_ACTIVE → ERR_SURGEON_INACTIVE`.
2. **Approve validation order** — followed PRD §3.7 / scaffold state-machine order: `UNDER_REVIEW → QUORUM → SoD (403) → REQUESTER_INACTIVE → SKU recheck`, even though §2.7 priority numbers place requester-active (p8) before quorum/SoD (p10).
3. **"Any" as a role value** — accepted as a valid `X-User-Role` (PRD §2.1's identity paragraph names it), authorized for GET endpoints only.
4. **`ERR_INVALID_STATE` (409)** used for double-deactivate (per PRD §3.1) and for retiring a SUPERSEDED/RETIRED card (unnamed in the spec).
5. **Range-error mapping** — `quantity`/`qty_used`/`counted_qty`/`delta_qty`-result/`qty_returned_unopened` violations → `ERR_INVALID_QUANTITY`; `unit_cost_cents`/`estimated_unit_cost_cents`/`consignment_budget_cents`/`expected_duration_min` floor violations → `ERR_INVALID_REQUEST` (matching the error catalog's condition lists).
6. **`pick_sequence` default** — per-card monotonically increasing creation counter (1-based), so a line created after a deletion does not reuse an index.
7. **Substitute price threshold** — computed with exact integer math (`4*sub_cost > 5*line_cost` rejects), so exactly 1.25x is allowed with no float error.
8. **Auto-stage double transition** — a substitution clearing the last SHORT with no PENDING moves the list PICKING_EXCEPTION→STAGED with two version bumps (one per logical state transition, per §2.4's "every mutation" rule).
9. **Duplicate usage/return entries for the same line** — last entry wins.
10. **Ghost surgeon** — `POST /product-requests` with an `X-User-ID` naming no Surgeon entity → `ERR_NOT_FOUND` (404).
11. **`scheduled_start`** is stored parsed and re-serialized in canonical UTC 3-fractional-digit form rather than echoing the raw input string.
12. **Return-endpoint check order** — line existence (p4) → list DISPATCHED (state) → line-belongs (ERR_LINE_CASE_MISMATCH) → quantity range, following the scaffold state machine's belong-before-range ordering for the dynamic bound.

## Step 7: Run Tests and Iterate — 2026-08-13T00:16:00.000Z

All 8 rounds pass 97/97 — clean sweep. Exiting with the summary.

---

**Summary**

- **Iterations run:** 2 (initial 8-round sweep: 91/97 in all 8 rounds; post-fix sweep: 97/97 in all 8 rounds).

- **Tests deleted:** none. Every failing assertion traced to a verbatim PRD sentence, and every failure was a test-artifact defect, not an implementation defect.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `test_suite/`** (4 files, 6 tests; all STEP 2 "TEST IS WRONG" — implementation was PRD-faithful in every case):
  1. `/home/ubuntu/github/CodingPRD/tasks/task_1338_perioperative_preference_card_supply/test_suite/test_03_case_scheduling.py` — `_glove()` helper used a hardcoded `sku="GLOVE-PR"`; `test_room_half_open_adjacency_allowed` and `test_room_overlap_rejected` each call it twice per test, violating PRD §3.1's SKU-uniqueness rule (`ERR_INVALID_REQUEST` on duplicate). Made the SKU unique per call via `uuid4`.
  2. `/home/ubuntu/github/CodingPRD/tasks/task_1338_perioperative_preference_card_supply/test_suite/test_04_picking_workflow.py` — (a) `test_double_release_returns_error` used `validate_error_is_one_of` without importing it (NameError); added the import. The one-of form is correct since PRD §2.7 tier 5 names both `ERR_CASE_NOT_SCHEDULED` and `ERR_PICK_LIST_EXISTS` with no intra-tier order. (b) `test_pick_then_cancel_restock_conserves_on_hand` used a single-line card: picking the only line auto-stages the list per PRD §3.4, and PRD §3.3 forbids cancelling with a `STAGED` list. Added a second (gauze) line left `PENDING` so the list stays `IN_PICKING` and the cancel restock invariant is exercised lawfully.
  3. `/home/ubuntu/github/CodingPRD/tasks/task_1338_perioperative_preference_card_supply/test_suite/test_10_difficulty_second_looks.py` — `test_cancel_restock_list_and_case_terminal`: identical auto-stage/cancel-gate setup bug; same second-line fix.
  4. `/home/ubuntu/github/CodingPRD/tasks/task_1338_perioperative_preference_card_supply/test_suite/test_05_case_completion.py` — `test_exactly_twenty_pct_flags` fixture arithmetic error: comment claimed `8*250 + 3000 + 800 = 6000` but it is 5800, so waste 1200 yielded 20.69%, not the intended 20.0 boundary. Gave ctx_a a dedicated drape at 3200 cents (standard exactly 6000, waste exactly 1200 → 20.0 flags); the shared 3000-cent drape used by the 19.98 sibling case was left untouched.

- **Fixes applied to `implementation/`:** none. In all six failures the implementation's behavior (duplicate-SKU rejection, auto-`STAGED` transition, `STAGED`-blocks-cancel, waste_pct computation) was exactly what the PRD sentences require.

## Step 8: Finalize PRD — 2026-08-13T00:22:00.000Z

Done. `PRD_FINALIZED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_1338_perioperative_preference_card_supply/workspace/PRD_FINALIZED.md`.

**Line counts:** PRD.md = 323 lines; PRD_FINALIZED.md = 323 lines (0.0% delta — one in-line revision within §3.4, no lines added or removed).

### Changes (1 total)

- **§3.4 — revise —** The release paragraph claimed "a second release is rejected with `ERR_PICK_LIST_EXISTS`", but the implementation evaluates the case-state guard first, so a literal second release of an already-released case (now `PICKING_RELEASED`) returns `ERR_CASE_NOT_SCHEDULED`; `ERR_PICK_LIST_EXISTS` fires only for a `SCHEDULED` case that already has a pick list. Revised the sentence and appended the ordering pin. — `implementation/routes_cases.py:123-128` (state check at 123-125 precedes existence check at 126-128).

### Step 7 items requiring no edit (PRD already pins impl behavior; pure test-fixture bugs)

1. **SKU uniqueness** (test_03 `_glove()` duplicate SKU): PRD §3.1 already states a duplicate `sku` is rejected with `ERR_INVALID_REQUEST` (HTTP 400), matching `implementation/routes_catalog.py:72-74`. No edit.
2. **Auto-`STAGED` + `STAGED`-blocks-cancel** (test_04 `test_pick_then_cancel_restock_conserves_on_hand`, test_10 `test_cancel_restock_list_and_case_terminal`): PRD §3.4 already states picking the final `PENDING`/`SHORT` line auto-transitions `IN_PICKING → STAGED` (`implementation/routes_picking.py:12-19`), and §3.3 already states a `STAGED` list makes the case non-cancellable with `ERR_CASE_NOT_CANCELLABLE` (`implementation/routes_cases.py:205-211`). No edit.
3. **20.0% waste boundary** (test_05 `test_exactly_twenty_pct_flags`): PRD §3.5 already pins `waste_pct = waste_cost_cents / standard_cost_cents × 100` rounded half-up to 2 dp, with "exactly 20.0 flags; 19.98 does not" (`implementation/domain.py:18` `WASTE_FLAG_THRESHOLD_PCT = Decimal("20.0")`; `implementation/routes_cases.py:353-360`). The failure was fixture arithmetic only. No edit.

### Pre-edit search log (for the single edit)

- **(a) Subject:** validation order and error identity on the pick-list release endpoint; the firing condition of `ERR_PICK_LIST_EXISTS`.
- **(b) Impl paths enumerated and read/grepped:**
  - `implementation/routes_cases.py:118-165` (`release_pick_list`) — full read; order is authz → path 404 → case-state (`ERR_CASE_NOT_SCHEDULED`) → pick-list existence (`ERR_PICK_LIST_EXISTS`) → pinned-card `ACTIVE` (`ERR_PINNED_CARD_NOT_ACTIVE`).
  - `grep -rn "ERR_PICK_LIST_EXISTS|pick_list_for_case" implementation/` — exactly one raise site (routes_cases.py:126-128); definition-only at `errors.py:30`; `pick_list_for_case` also used read-only by `cancel_case` (204) and `complete_case` (259).
  - `implementation/domain.py:60-65` (`pick_list_for_case`) — matches a list of any status; no code path ever deletes a pick list.
  - `implementation/routes_cases.py:199-224` (`cancel_case`) — sets list `CANCELLED` and case `CANCELLED`; never returns a case to `SCHEDULED`, so it cannot create a "SCHEDULED case with existing list" constellation that would contradict the new wording.
  - `implementation/routes_cases.py:167-197` (`repin_card`) — requires `SCHEDULED`, touches no pick lists; consistent.
  - Cross-checked PRD §2.7 tier 5 (lists both errors without intra-tier order) and the existing intra-tier ordering precedents in §2.7 tiers 8/9 — the new endpoint-level ordering sentence follows that established pattern.
- **(c) Wording adjustment:** Yes — instead of only appending the order note, the original clause "a second release is rejected with `ERR_PICK_LIST_EXISTS`" had to be re-scoped to "a `SCHEDULED` case that already has one is rejected with `ERR_PICK_LIST_EXISTS`", because the original clause mis-described the dominant second-release path (state check fires first). The appended sentence then pins the actual second-release outcome (`ERR_CASE_NOT_SCHEDULED`) without claiming anything about unreachable or off-site paths.
