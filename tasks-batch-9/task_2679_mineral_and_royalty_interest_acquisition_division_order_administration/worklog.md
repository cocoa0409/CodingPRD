# Worklog — task_2679_mineral_and_royalty_interest_acquisition_division_order_administration

## Step 1: Create task directory — 2026-09-04T05:41:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2679_mineral_and_royalty_interest_acquisition_division_order_administration/` and its `workspace/` subdirectory. Index 2679 was pre-assigned by the orchestrating command; no scan of ./tasks/ was performed.

## Step 2: Generate scaffold (subagent) — 2026-09-04T07:06:00.000Z

All three artifacts are complete and `scaffold_lint.py` reports clean.

Lint verdict, verbatim:

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           .../SCAFFOLD.yaml
  Difficulty design:  .../SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      .../SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    59
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     57
  Calls scanned (§1.8+§1.9):  842

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Deliverables

| File | Lines |
|---|---|
| SCAFFOLD.yaml | 3020 |
| SCAFFOLD_DIFFICULTY_DESIGN.yaml | 1757 |
| SCAFFOLD_CORNER_DESIGN.yaml | 3615 |

SCAFFOLD.yaml counts (§1.0–§1.7 only; neither design key present): 13 entities, 8 state machines, 2 concurrency rules, 10 calculations, 51 validation rules (priority-ordered), 59 endpoints, 59 error codes, 6 roles (TitleAnalyst, AcquisitionManager, DivisionOrderAdmin, Operator, RoyaltyOwner, PlatformAdmin).

SCAFFOLD_DIFFICULTY_DESIGN.yaml: single key `scaffold_difficulty_design`, 9 rule blocks x 2 = 18 instances (meets the >= 2 per rule / >= 18 total minimum).

SCAFFOLD_CORNER_DESIGN.yaml: single key `scaffold_corner_design`, 9 grouped sections, 80 instances = 57 with full `test_recipe` + 23 `excluded_because:` stubs. Per section: entities 12, state_machines 10, calculations 10, validations 13, endpoints 5, errors 14, rbac 7, cross-cutting complexity layers 7, consistency model 2. All 23 stubs resolve to real `- name:` entries in the difficulty file; no duplicate corner names.

Consistency checks run beyond the linter: all 59 error codes are cited by at least one instance across the two design files, and all 59 are referenced by a validation rule, transition or concurrency rule in SCAFFOLD.yaml. One SCAFFOLD.yaml fix was needed during authoring: validation priorities 72 (ERR_NO_ACTIVE_ALLOCATION) and 74 (ERR_TRACT_UNIT_MISMATCH) originally overlapped so 74 was unreachable; their `check` texts are now explicitly disjoint (74 fires when no allocation row exists for the (unit, tract) pair, 72 only once one does). All three files parse with `yaml.safe_load`. No sibling task directory was read, and `workspace/`/`worklog.md` were left untouched.

## Step 3: Copy shared files — 2026-09-04T07:07:00.000Z

Copied ./INSTRUCTION.md to tasks/task_2679_.../workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD (subagent) — 2026-09-04T07:20:00.000Z

PRD generated and verified.

**Output:** `.../workspace/PRD.md` — 484 lines / 101 KB, ending cleanly at the last row of the §5 error table (no audit footer, no scaffold-internal references such as `calculations.*` or `§1.x`).

**Sections**
- §1 Introduction (3 paragraphs)
- §2 Global Specifications — 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verified byte-identical to `section-2.2-response-structure.md`) · 2.3 Pagination · 2.4 Resource Identity, Audit Columns and the Logical Clock · 2.5 Precision: Acres, Dollars, Fractions and Decimal Interests · 2.6 Segregation of Duties · 2.7 Optimistic Concurrency on Parent Interests and Units · 2.8 Path Resolution and Reference Integrity · 2.9 Conserved Quantities · 2.10 Order of Validation · 2.11 Cascade Semantics and Version Propagation
- §3 Business Logic & Workflows — 9 subsections: 3.1 Chain of Title · 3.2 Owners of Record, Mineral Interests and the Decline-Curve Valuation · 3.3 Offer Negotiation · 3.4 Papering the Agreement and its Exclusive Occupancy Window · 3.5 The Curative Period and the Basket Waterfall · 3.6 Funding, Deed Recording and the Ownership-Change Cascade · 3.7 Unitization, Acreage Commitments and Pugh Elections · 3.8 Division Orders · 3.9 Revenue Reconciliation, Suspense Resolution and Owner Reporting
- §4 Endpoint Definitions (4-column table, **59 rows**)
- §5 Error Code Catalogue (2-column table, **59 rows**)

**Hard contracts (machine-checked against SCAFFOLD.yaml):**
```
Field coverage check:
- entities[].fields: 133 required, 133 present, 0 missing
- endpoints[].input/request_body/query_params/output keys: 94 required, 94 present, 0 missing
- state enumeration values: 34 required, 34 present, 0 missing
- enum-type field values: 69 required, 69 present, 0 missing
- roles[].name: 6 required, 6 present, 0 missing
- errors[].id: 59 required, 59 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 51 checked, 51 expressed in prose (full §2.10 ordered ladder with error id, status and applies_to scope per rung), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_mineral_interest_version / expected_unit_version + error_id + 412), 0 missing
- state_machines[].transitions: 8 machines / 34 transitions checked, all fully expressed with from/to, preconditions paired to error ids, and every side effect, 0 missing
- calculations[]: 10 checked, 10 fully expressed in prose (pinned rounding orders, all constants embedded: 0.2500 burden cap, 5-year horizon at 10%, $1,800/acre × 0.45 × {1.20/1.00/0.80}, 30% non-consent penalty, 20% termination ceiling, per-state severance rates, 6% suspense interest, 36-month escheat, 15% depletion capped at 65%, 30-day PSA buffer, 3 counter rounds), 0 missing
- validations[] conditions: 51 checked, 51 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 59 checked, expressed, 0 missing
- entities[].fields[] structured content: 133 checked, defaults/initial values/nullability/precision reconstructible, 0 missing
- sibling-branch symmetry: 6 groups checked (offer counter/accept from SENT vs REVISED, cure-loop edges, curative CLOSED vs TERMINATED, division-order branch A vs B, release vs escheat, pdp_only vs risked_upside), equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 953
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Also confirmed: no fuzzy/approximating words ("approximately", "roughly", "conservatively", "about", "~") anywhere in the document; the two withheld design files were never opened, and no sibling `task_*/` directory was read.

Orchestrator truncation check: `tail -c 1200` shows the document ending at the final error-table row (`ERR_CORRECTED_DECIMAL_MISMATCH | 422`) — a real section boundary. No regeneration needed.

## Step 6: Generate implementation (subagent) — 2026-09-04T08:11:00.000Z

Implementation complete and verified.

## Files written (all under `.../workspace/implementation/`)

| File | Lines |
|---|---|
| `app.py` | 63 |
| `errors.py` | 142 |
| `db.py` | 152 |
| `response.py` | 46 |
| `guards.py` | 318 |
| `calc.py` | 307 |
| `serializers.py` | 306 |
| `services/__init__.py` | 0 |
| `services/cascade.py` | 173 |
| `routes/__init__.py` | 0 |
| `routes/tracts.py` | 184 |
| `routes/owners.py` | 97 |
| `routes/interests.py` | 224 |
| `routes/offers.py` | 144 |
| `routes/psas.py` | 271 |
| `routes/defects.py` | 113 |
| `routes/units.py` | 254 |
| `routes/dorders.py` | 244 |
| `routes/suspense.py` | 83 |
| `routes/clock.py` | 24 |
| `requirements.txt` | 1 |
| `start.sh` | 11 (chmod +x) |

**3157 lines of Python total.** `python3 -m compileall -q` is clean; `__pycache__` removed.

## Endpoint count
**59 of 59** endpoints registered — verified by enumerating `app.url_map` (matches the SCAFFOLD endpoint count exactly).

## Fix applied this session
`app.py` imported `message_for` from `errors.py`, which did not define it — an import-time `ImportError` that would have made every single per-test-server boot fail. Added `def message_for(error_id): return DEFAULT_MESSAGES.get(error_id, error_id)` to `errors.py`.

## Smoke-test result: pass
Launched `PORT=18380 bash start.sh` in the background and drove five full business flows via curl. Zero tracebacks and **zero HTTP 500s** in the server log across ~90 requests; the observed status mix was 200/201 plus deliberate 400/403/404/409/412/422.

Verified working end to end:
- chain-of-title replay → certify (`net_mineral_acres_certified` 500.0000, `existing_burden_fraction` 0.0500 on a 640-acre tract)
- decline-curve valuation band (`pdp_pv`/`undeveloped_pv`/`bid_floor`/`max_bid`), offer issue → counter → revise → accept / reject
- segregation of duties on offer issuance (issuer ≠ valuation approver) and on suspense release (releaser ≠ order creator)
- both OCC rungs: `ERR_STALE_INTEREST_VERSION` and `ERR_STALE_UNIT_VERSION` → 412
- PSA creation, defect basket waterfall, cure submit → decision → waive, both curative branches (`CURATIVE_CLOSED` and `CURATIVE_TERMINATED`), funding-amount mismatch
- **3-hop curative-termination cascade**: interest → `PROSPECT`, offer → `VOIDED`, valuation → `STALE`
- **4-hop deed-recording cascade**: PSA → `CLOSED`, interest → `ACQUIRED` with `acquiring_deed_book_page`
- unit formation, allocation half-open interval overlap rejection, pugh release (deadline gate fires correctly before/after the logical clock passes it) with acreage conservation preserved (1280 gross / 1120 unallocated after a 160-acre release), allocation termination
- division order issue → operator response (both agree and dispute branches) → correct with `ERR_CORRECTED_DECIMAL_MISMATCH`
- revenue reconciliation with per-state severance rates (TX oil 0.046, TX gas 0.075), PAID routing, `DECIMAL_VARIANCE` and `UNLOCATABLE_OWNER` suspense routing
- suspense release with interest accrual, escheat with the 36-month dormancy gate
- owner annual tax statement (depletion allowance capped at 65% of taxable income)
- logical clock `POST /_clock/set_current_utc`, pagination bounds, per-kind 404s, 401 on missing auth headers

The server pid was killed individually (`kill 2946697`); port released, no broad pattern kill used. One incidental finding worth noting: `start.sh` correctly `exec`s into a single `python3 app.py` process, so the pid the harness spawns *is* the server and is directly killable — no orphan child is left holding the port between per-test reboots.

## Step 5: Generate unit tests (subagent) — 2026-09-04T08:20:00.000Z

Stage 1 and Stage 2 are complete for task 2679.

## Output locations (task root, never under `workspace/`)

`/home/ubuntu/github/CodingPRD/tasks/task_2679_mineral_and_royalty_interest_acquisition_division_order_administration/`

**`test_helpers/`** (Stage 1, 1,770 lines): `__init__.py` 93, `api_client.py` 266, `api_errors.py` 82, `assertions.py` 191, `constants.py` 83, `factories.py` 276, `fixtures.py` 434, `test_users.py` 84, `types.py` 261.

**`test_suite/`** (Stage 2, 3,942 lines incl. `conftest.py` 51):

| file | lines | tests |
|---|---|---|
| test_01_valuation_bid_band | 108 | 4 |
| test_02_revenue_pinned_versus_live | 104 | 4 |
| test_03_expected_decimal_branches | 60 | 2 |
| test_04_defect_basket_waterfall | 72 | 2 |
| test_05_offer_negotiation_cycle | 104 | 4 |
| test_06_psa_dimensions | 90 | 3 |
| test_07_record_deed_cascade | 110 | 4 |
| test_08_curative_termination_cascade | 75 | 2 |
| test_09_validation_priority_pairs | 148 | 6 |
| test_10_boundary_precision | 96 | 4 |
| test_11_cross_entity_state | 158 | 6 |
| test_12_temporal_overlap | 188 | 6 |
| test_13_conserved_quantities | 184 | 6 |
| test_20_entity_surface | 374 | 13 |
| test_21_state_machines | 309 | 9 |
| test_22_calculations | 182 | 6 |
| test_23_validations | 351 | 12 |
| test_24_endpoints | 169 | 6 |
| test_25_errors | 441 | 15 |
| test_26_rbac | 209 | 8 |
| test_27_layers | 283 | 10 |
| test_28_consistency | 71 | 2 |

**134 tests total.**

## Design-index coverage (machine-audited)

- Queue A (§1.8): **18/18** non-stub difficulty instances translated, every one with ≥2 tests. 0 stubs in that index.
- Queue B (§1.9): **57/57** non-stub corner instances translated, each with ≥1 test; all **23** `excluded_because:` stubs left untranslated (verified none carries a tag).
- Tag hygiene: 134 tests / 134 `Design:` lines — exactly one per test, always the last docstring line, no untagged, dual-tagged, or dangling tags (a script cross-checks every tag against the parsed yaml keys; 0 problems). Found and fixed one mis-tag: `test_10` had `Design: Corner/boundary_precision_check/...` for what is a §1.8 rule, now `Design: Difficulty/...`.
- **Instances skipped: 0.** Every non-stub instance survived the PRD-first filter.

## Audits run

- **PRD-citation pass**: 142 quoted sentences extracted from docstrings and matched whitespace-normalised against `workspace/PRD.md` — 0 non-verbatim, none abbreviated below the rule-bearing threshold. Three citations were rewritten during this pass after failing the verbatim check (an invented accept-offer sentence, and two invented §2.4 version/`updated_at` sentences).
- **Scaffold-leak pass**: 0 hits for `scaffold`, `§1.x`, `test_recipe`, `claim_type`, `validations[priority`, `excluded_because`, `grounds:`, etc. outside the `Design:` tag lines.
- **Static reference check**: AST walk verifies every `fx.*`, `f.*`, `api.*` and `from test_helpers…import` name resolves against the real modules — 0 missing.
- `pyflakes` clean on `test_suite/` (one unused import removed from `test_26`); `python3 -m compileall -q test_helpers test_suite` → COMPILE_OK.

## PRD-over-design corrections carried into the tests

- Design recipes using `MISSING_PROBATE` / `UNRELEASED_LIEN` as `defect_type` were retargeted to the PRD enum (`MISSING_HEIR`, `UNRELEASED_LEASE`, …).
- `escheat_eligible` is asserted nowhere: the design index references it but the PRD never declares it. `months_held` / `interest_accrued` / `release_amount` carry those instances instead.
- The design's "data is null in every error envelope" claim was dropped: the framework's `validate_error` proves `data.error_id` and `data.message`, so the assertion would contradict the harness contract.
- `chain_with_probate_before_deed_is_rejected_as_acreage_negative` is asserted at certification, not at insert (PRD line 216: filing never rejects for negative acreage).
- Recipes that call `certify-title` without filing a `PATENT` first were built through `fx.create_certified_tract` / composite fixtures so they do not trip `ERR_TITLE_CHAIN_INCOMPLETE`.

Orchestrator note: Steps 5 and 6 were launched as background agents. The Step 5 launch tool-call returned before the Step 6 call could be placed in the same assistant message, so Step 6 started roughly one minute later; both then ran concurrently in wall-clock. Physical isolation was preserved by an explicit hard prohibition in the Step 6 prompt against reading `test_helpers/`, `test_suite/`, or either design index, and the Step 6 summary confirms it built only from INSTRUCTION.md + SCAFFOLD.yaml + PRD.md.

## Step 7: Run tests and iterate (long-lived subagent) — 2026-09-04T08:40:00.000Z

Clean. Final state confirmed.

## Summary

**Iterations run: 2.** Iteration 1 showed a deterministic 131/134 in all 8 rounds (same 3 failures every round — no flakiness anywhere in the suite). Iteration 2 is a clean sweep.

**Tests deleted: none.** All three failures were test-layer bugs whose core rules are verbatim in the PRD, so all three were repaired rather than removed. One *assertion* was removed under STEP 1c partial-coverage handling (below).

**Fixes applied to `test_suite/`** (no `test_helpers/` change was needed — none of the three bugs lived in a shared fixture):

1. `test_23_validations.py::test_a_unit_may_be_committed_to_the_acre_but_not_past_it` — the third tract was built as `fx.create_certified_tract(api, gross_acres=320.0000, ...)`, but `add_canonical_chain` files a `DEED` of `conveyed_acres` 480.0000. On a 320-acre tract the chronological replay goes `PATENT → 320.0000`, then `DEED → -160.0000`, so the PRD-faithful implementation correctly refused certification with `ERR_CHAIN_ACREAGE_NEGATIVE` (§2.10 rung 38 / §3.1). Dropped the `gross_acres` override so the tract uses the canonical 640.0000 that the shared chain is tuned for. Nothing in the test depends on the third tract's acreage — it exists only to contribute the extra 0.0001 acre that must oversubscribe the unit.
2. `test_23_validations.py::test_a_defect_cannot_impair_more_acreage_than_was_bought` — trailing assertion read `read_psa(...)["open_defect_count"] == 1`. **PRD-silence category: COMPUTED-FIELD / field-surface silence.** `open_defect_count` appears nowhere in PRD.md (grep: 0 hits), and §3.4 enumerates the agreement's fields explicitly without it, so a faithful reader correctly omits it from the serializer. Per STEP 1c the covered assertions were kept (the 422 `ERR_DEFECT_ACREAGE_EXCEEDS_INTEREST` for 50.0000 > 40.0000, and the exact-equality acceptance at 40.0000 — both verbatim in §3.5) and the uncovered one was replaced with `assert_acreage(exact["affected_nma"], "40.0000", ...)`, which checks a field §3.5 does declare. Scaffold rule that drove it: `Corner/validations/defect_acreage_above_interest_net_acres_is_rejected`.
3. `test_27_layers.py::test_issuing_an_order_does_not_write_the_unit` — asserted the parent unit's `version` was unchanged after issuing a division order, and cited an unrelated PRD sentence about amendments not re-running decimals. PRD §3.8 states verbatim: *"Issuing an order increments the unit's `version` by 1."* The assertion mis-translated the PRD; the implementation was right. Fixed the assertion to `== before + 1`, replaced the docstring quote with the governing verbatim sentence, and renamed the test to `test_issuing_an_order_advances_the_parent_unit_version_by_one`.

**Fixes applied to `implementation/`: none.** No PRD-required check was weakened or removed; no endpoint, field, or side effect was added. Verified the implementation carries no on-disk persistence and no startup seeding (storage is in-memory dicts only).

**Final per-round results**, quoted from `workspace/implementation/results.$i.json`:

| round | passed / total | failed | errors |
|---|---|---|---|
| 1 | 134 / 134 | 0 | 0 |
| 2 | 134 / 134 | 0 | 0 |
| 3 | 134 / 134 | 0 | 0 |
| 4 | 134 / 134 | 0 | 0 |
| 5 | 134 / 134 | 0 | 0 |
| 6 | 134 / 134 | 0 | 0 |
| 7 | 134 / 134 | 0 | 0 |
| 8 | 134 / 134 | 0 | 0 |

Test count held at 134 throughout (collection verified before and after the edits), so no coverage was lost. Notably the suite showed zero timing sensitivity — both sweeps were bit-identical round to round, so the host contention caveat never came into play.

Orchestrator verification: independently re-read all 8 `results.$i.json` (each ~42 KB, mtime 08:26) and confirmed `passed=134 total=134 failed=0 errors=0` in every round. Artifacts are real, not a subagent claim.

Orchestrator decision on Step 8: Step 7 applied **0 `implementation/` fixes and 0 deletions**, but it did apply 3 `test_suite/` fixes, one of which (`open_defect_count`) is a genuine PRD field-surface silence and one of which (`test_27_layers`) was a PRD-vs-test mismatch the implementation resolved correctly. The skip condition requires 0 fixes across *all four* categories, so it is not met — Step 8 runs.

## Step 8: Finalize PRD (subagent) — 2026-09-04T08:56:00.000Z

Done. `PRD_FINALIZED.md` is a one-sentence patch of `PRD.md`.

## Line counts
- `PRD.md`: 484 lines / 101,076 bytes
- `PRD_FINALIZED.md`: 484 lines / 101,345 bytes
- Line delta: 0 (0.0%); byte delta +269 (+0.27%). Structure verified intact: §1–§5 with all 28 headings, 59-row endpoint table, 59-row error table, file ends on the last error row (`ERR_CORRECTED_DECIMAL_MISMATCH | 422`).

## Changes (1)
- **§3.4 (Papering the Agreement)** — *insert* — appended to the agreement-read sentence: the agreement's representation carries no defect counter of any kind (no tally of open/raised/uncured/cured/waived defects), and a caller needing such a count lists the agreement's defects and reads `total_count` from that listing's `meta` — `implementation/serializers.py:125-147` (`psa_out`), `implementation/response.py:30-35`.

## Per-edit pre-edit search log
**Edit 1 — §3.4 defect-counter absence** (traces to step_7_diff item 2, the removed `read_psa(...)["open_defect_count"] == 1` assertion)
- (a) Subject: the agreement (PSA) response field surface, specifically any defect roll-up/count field on it.
- (b) Paths enumerated: `serializers.py:125-147` `psa_out` (exact field set — no counters); `routes/psas.py:74-101` `create_psa` row literal, `:188-221` `close_curative`, `:224-243` `fund_psa`, `:246-271` `record_deed` (no counter key is ever written to a psa row); `services/cascade.py:17-26` `recompute_psa_status`, `:32-55` `curative_termination_cascade`, `:101-125` `recording_cascade` (never add fields to psa rows); `routes/defects.py:53-113` (submit-cure / cure-decision / waive mutate only the defect row, never the psa); `routes/psas.py:173-185` `list_defects` + `response.py:30-35` (the only defect count in the system is the pagination `meta.total_count`, matching §2.3); repo-wide `grep -rn "_count"` over `implementation/` to enumerate every count-bearing field (tract `chain_entry_count`, offer `counter_round_count`, defect `cure_round_count`, unit `producing/total_depth_count` + `active_allocation_count`, order `correction_round_count`, suspense `held_detail_count`, tax statement `detail_count`) — confirming none live on the agreement.
- (c) Wording adjustment: my first draft also asserted "the agreement's representation is exactly the fields named in this subsection plus the §2.4 audit properties." I removed that universal, because §3.4 also names `expected_mineral_interest_version` (a request-only field absent from `psa_out`), so the claim would have created a new mismatch. The committed sentence is the narrow negative claim only, and it is scoped to "the agreement's representation" so it does not contradict the defect's own `cure_round_count` or the defect-listing `meta.total_count`.

## Items that needed no PRD change
- **Item 1 (tract `gross_acres` fixture override)** — pure fixture bug. §3.1 already pins the replay verbatim (PATENT replaces with `gross_acres × conveyed_fraction`, DEED subtracts `conveyed_acres`, PROBATE multiplies, ASSIGNMENT is a no-op; round half-up to 4dp after every step; below zero at any step → `ERR_CHAIN_ACREAGE_NEGATIVE`), matching `calc.py:82-98`; §2.10 rung 38 fixes its precedence. The unit-capacity rule the test exercises is likewise verbatim in §3.7 and matches `routes/units.py:156-177`.
- **Item 3 (unit `version` after issuing an order)** — the PRD sentence "Issuing an order increments the unit's `version` by 1" (§3.8) already matches `routes/dorders.py:65` (`touch(unit)`); the test had mis-translated the PRD, so nothing to pin.

## Step 9: Complete PRD (three sequential file-partitioned subagent passes) — 2026-09-04T09:25:00.000Z

Orchestrator note on method: Step 9 was run as three sequential passes over disjoint partitions of `implementation/`, each editing `workspace/PRD_COMPLETED.md` in place with targeted Edit calls. A single-agent full-implementation scan on a 59-endpoint / 3157-line codebase reliably either truncates the output PRD or degenerates into a byte-identical copy of its input; partitioning keeps each pass's working set small enough to walk exhaustively. Partition: pass 1 = app/response/errors/db/guards/serializers + routes/{clock,tracts,owners,interests}; pass 2 = calc + services/cascade + routes/{offers,psas,defects}; pass 3 = routes/{units,dorders,suspense} + two cross-pass hand-offs.

### Pass 1 summary (subagent, verbatim)

PASS 1 complete. `PRD_COMPLETED.md` written.

- **Source** `PRD_FINALIZED.md`: 484 lines / 101,345 bytes
- **Result** `PRD_COMPLETED.md`: 486 lines / 108,304 bytes — **char delta +6,959**, 16 source lines touched (+2 new lines from one new paragraph inside §2.5)
- **Ambiguity pins: 15** · **Mismatch revisions: 3**

Changes:
- `§2.1` — revise — ambiguity — `X-User-ID` that is empty *or whitespace-only* counts as missing → 401 — `guards.py:35-37`
- `§2.2` — revise — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A–Z0–9`, fresh per request — `response.py:10-14`
- `§2.2` — revise — mismatch — `api_request_timestamp` reads the **host** clock, not the logical clock — `response.py:18`, `db.py:62-63`
- `§2.3` — revise — ambiguity — empty-string `limit`/`offset` = absent; non-integer = `ERR_INVALID_REQUEST`; `offset` unbounded, past-end page is 200 with empty array, full `total_count`, `has_more` false — `guards.py:222-245`, `response.py:30-37`
- `§2.3` — revise — ambiguity — `created_at` ties broken by server insertion order (all orderings total/stable) — `db.py:20-22,147-152`
- `§2.3` — revise — ambiguity — filter params are exact string compares, **not** enum-validated (bad value → empty page, not 400); undeclared query params ignored — `tracts.py:61-67`, `owners.py:52-58`, `interests.py:78-87`
- `§2.4` — revise — mismatch — `created_at`/`updated_at` stamped from the host clock; only `certified_at` and `accepted_at` come from the logical clock — `db.py:121-144`, `tracts.py:166`
- `§2.4` — revise — mismatch — "never the host's wall clock" narrowed to business time, with the two documented exceptions — `db.py:62`, `response.py:18`
- `§2.4` — revise — ambiguity — `current_utc` accepted grammar (`T` or space, optional fraction, optional `Z`/`±HH:MM` normalised to UTC); response is 200 with a one-key `data` echoing the raw string verbatim — `db.py:87-115`, `routes/clock.py:18-24`
- `§2.5` — insert (new paragraph) — ambiguity — excess input precision is rounded half-up at ingest, never rejected; range tests run on the *raw* value first (`gross_acres` `0.00001` → stored `0.0000`); figures travel as JSON numbers with no trailing-zero preservation (`100.0`), unset → `null` — `guards.py:111-137`, `serializers.py:11-16`
- `§2.8` — revise — ambiguity — unmatched path → `ERR_INVALID_REQUEST` **404**; wrong method → `ERR_INVALID_REQUEST` **405**; trailing slash insignificant — `app.py:22,33-40`
- `§2.8` — revise — ambiguity — multiple body refs resolve in payload-declaration order (`tract_id` before `seller_owner_id`); an absent/null/non-string ref is a rung-7 400, never a 404 — `guards.py:308-318`, `interests.py:32-39`
- `§2.8` — revise — ambiguity — numeric fields must be JSON numbers (numeric strings and booleans rejected; integer fields reject fractions); missing/unparseable body = empty object; non-object body = 400; undeclared fields ignored; any escaped failure is `ERR_INVALID_REQUEST` 400 — no 5xx anywhere — `guards.py:49-55,98-108,145-155`, `app.py:42-53`
- `§3.1` — revise — ambiguity — "must be null" satisfied by omission *or* explicit null; `instrument_date` unconstrained vs the clock — `guards.py:214-216`, `tracts.py:82-91`
- `§3.2` — revise — ambiguity — PATCH owner with no amendable field is not an error; still refreshes `updated_at` and bumps `version` — `owners.py:69-79`
- `§3.2` — revise — mismatch — owner read is a plain role check with **no** rung-4 identity comparison ("the `RoyaltyOwner` itself" → any `RoyaltyOwner`) — `owners.py:43-45`
- `§3.2` — revise — ambiguity — no interest-posture gate on filing a valuation (any of the five postures) — `interests.py:97-115`
- `§3.3` — revise — ambiguity — `expires_on` may pre-date the clock; issuance never raises `ERR_OFFER_EXPIRED` — `interests.py:175-190`
- `§3.9` — revise — ambiguity + mismatch — `tax_year` is a required query param, integer 1–9999, else 400; tax-statement read carries no rung-4 identity check — `owners.py:85-96`

Structural check confirmed: §1–§5 all present; 28 markdown headings; endpoint table 59 rows; error table 59 rows; final line is exactly ``| `ERR_CORRECTED_DECIMAL_MISMATCH` | 422 |``. No sections or headings added; every change an in-paragraph insert/revision except one new paragraph in §2.5. Verified via `diff`: exactly the 16 intended lines changed.

### Pass 2 summary (subagent, verbatim)

PRD_COMPLETED.md before pass 2: 486 lines / 108,304 bytes → after: 486 lines / 113,441 bytes (line count unchanged; every edit an in-paragraph insert or revision).
**ambiguity-pins: 16 · mismatch-revisions: 3**

- §3.2 (¶ bid band) — revise — mismatch — the PRD asserted `max_bid` − `bid_floor` equals `undeveloped_pv` × haircut rounded to cents; impl rounds the *summed* PVs once, so the two can differ by a cent (e.g. pdp_pv=1.10, und_pv=1.10, haircut=0.9950 → floor 1.09, max 2.19, diff 1.10 ≠ 1.09). Now states max_bid is the single haircut-and-round of the sum and the difference can land a cent away — `calc.py:126-135`
- §3.8 (¶ four factors) — insert — ambiguity — ownership and participation quotients are carried at full working precision, not rounded to the 6-decimal fraction precision of §2.5 — `calc.py:171-172`
- §3.9 (¶ depletion) — insert — ambiguity — the two depletion candidates are compared unrounded and only the winner is rounded to cents — `calc.py:283-285`
- §3.5 (¶ termination cascade) — insert — ambiguity — the interest's `current_valuation_id` is not cleared and keeps pointing at the now-`STALE` valuation — `services/cascade.py:52-55`
- §3.6 (¶ recording cascade, hop 3) — insert — ambiguity — the `expected_decimal`/`allocation_id` recompute is best-effort: any of the three selector failure modes silently leaves both fields as they stood and the cascade continues; `pinned_decimal`, `operator_decimal`, `effective_production_month` and `correction_round_count` are untouched — `services/cascade.py:119-123`
- §3.9 (¶ escheat, closing sentence) — revise — mismatch — PRD flatly called `RELEASED`/`ESCHEATED` terminal; `upsert_suspense` reuse drives the row back to `ACCRUING` on a later variance hold or ownership-transfer cascade, preserving `suspense_reason`, `first_suspended_month`, `released_by_user_id` and `escheat_state_code` — `services/cascade.py:92-95`
- §3.9 (¶ release) — insert — ambiguity — `do_status = EXECUTED` is unconditional, so a `DISPUTED` order with an `OWNERSHIP_TRANSFER` account is forced to `EXECUTED` without ever being `SUSPENDED`, and `dispute_reason` and the three decimals are not rewritten — `services/cascade.py:169-172`
- §3.9 (¶ suspense recomputation) — revise — mismatch — PRD said the four figures recompute "on every read"; `serializers.refresh_suspense` short-circuits for non-`ACCRUING` accounts, so they freeze after release/escheat — `serializers.py:262-263`
- §3.3 (¶ counter) — insert — ambiguity — `counter_amount` is only `> 0` at 2 dp and faces no bid-band test at all — `routes/offers.py:68`
- §3.3 (¶ revise) — insert — ambiguity — the revised `expires_on` is unconstrained against the logical clock and need not be later than the date it replaces — `routes/offers.py:89,104`
- §3.3 (¶ accept) — insert — ambiguity — acceptance does not touch the mineral interest: it stays `OFFERED` and its `version` does not move — `routes/offers.py:120-123`
- §3.3 (¶ reject) — insert — ambiguity — an omitted/null `rejection_reason` leaves the stored field as it stood rather than clearing it — `routes/offers.py:139-140`
- §3.6 (¶ funding) — insert — ambiguity — `wire_amount` is at least zero at 2 dp; `wire_reference` is a non-empty string with no format or uniqueness rule — `routes/psas.py:229-230`
- §3.6 (¶ record deed) — insert — ambiguity — `recording_county` and `recorded_book_page` need only be non-empty; unlike `county_book_page` there is no `digits/digits` format and no uniqueness check — `routes/psas.py:251-252`
- §3.5 (¶ raise defect) — insert — ambiguity — the acreage test is per-defect and never cumulative — `routes/psas.py:149-150`
- §3.5 (¶ defect creation fields) — insert — ambiguity — a defect also opens with a null `decision_note` and a null `waiver_note` (both appear in its representation) — `routes/psas.py:165-166`
- §3.5 (¶ submit cure) — insert — ambiguity — `cure_instrument_book_page` has no citation format, and there is no ceiling on `cure_round_count` (contrast the three-counter offer cap) — `routes/defects.py:59,68`
- §3.5 (¶ cure decision) — insert — ambiguity — `decision_note` is written only when supplied; omitted/null leaves an earlier round's note standing — `routes/defects.py:89-90`
- §3.5 (¶ waive) — insert — ambiguity — `waiver_note` likewise written only when supplied — `routes/defects.py:110-111`

Structural check confirmed: 486 lines / 113,441 bytes; 28 headings; §1–§5 at lines 3, 11, 206, 356, 422; 59 endpoint rows; 59 `ERR_` rows; final line exactly the `ERR_CORRECTED_DECIMAL_MISMATCH | 422` row. No pass-1 edit reverted.

### Pass 3 summary (subagent, verbatim)

PRD_COMPLETED.md before: 486 lines / 113,441 bytes → after: 486 lines / 119,051 bytes.
**8 mismatch-revisions, 13 ambiguity-pins** (21 Edit calls).

Mismatches:
- §2.1 — revise — mismatch — "Any operator write against a unit, one of its allocations, or one of its division orders … is rejected with `ERR_NOT_RESOURCE_OWNER`" was false; now names exactly the four rung-4 writes and states that amending a unit, committing acreage and reporting revenue detail are role-gated only — `routes/units.py:101,131`, `routes/dorders.py:148` (no `_require_operator`) vs `units.py:211,240`, `dorders.py:94,119`
- §3.7 ¶1 — revise — mismatch — same over-broad `operator_user_id` claim narrowed to the four rung-4 writes — `routes/units.py:25`
- §2.10 rung 44 — revise — mismatch — hand-off (a): guard list extended to "issuing a division order **and correcting one**", with the reason it cannot fire on a correction — `routes/dorders.py:129` → `calc.py:146`
- §3.8 ¶ operator response — revise — mismatch — "production months earlier than it are not reported against this order" is not enforced anywhere; now stated as a record kept for reporting only, never a gate — `routes/dorders.py:146` (no month comparison)
- §3.9 ¶ held-line cascade — revise — mismatch — accrual described as "`net_amount` added / `held_detail_count` increments by 1"; impl recomputes wholesale, which differs on a reopened account — `services/cascade.py:90,93` → `serializers.py:260`
- §3.9 ¶ suspense figures — revise — mismatch — "Four of its figures" / "all four figures" / "four clock-sensitive figures" corrected to five; `refresh_suspense` recomputes `accrued_amount`, `held_detail_count`, `months_held`, `interest_accrued`, `release_amount` — `serializers.py:260-275`
- §2.9 revenue identity — insert — mismatch — the identity does **not** hold across an escheat (accrued zeroed, lines stay `VARIANCE_HELD`, `paid_net_total` unmoved); noted as the one deliberate exception — `routes/suspense.py:77-81`
- §3.8 ¶ correction — insert — mismatch-adjacent — `pinned_decimal`, `effective_production_month` and the unit's `version` are explicitly untouched by a correction — `routes/dorders.py:133-139`

Ambiguity pins:
- §3.7 ¶2 — insert — ambiguity — PATCH surface: those four fields are the whole amendable set, others immutable/ignored; `producing_depth_count` re-tested against stored `total_depth_count`; activating `pugh_clause_active` needs a stored-or-same-request deadline else `ERR_INVALID_REQUEST`; explicit null = absent so a deadline can never be cleared; an empty payload still increments `version` — `routes/units.py:99-123`
- §3.7 ¶4 — revise — ambiguity — a unit's allocation list returns every posture including `TERMINATED` unless filtered — `routes/units.py:188-203`
- §3.7 ¶last — insert — ambiguity — `termination_reason` is a required non-empty string; a terminated row keeps its `allocated_acres`/`released_acres` rather than zeroing them — `routes/units.py:242,247-249`
- §3.8 ¶ operator response — insert — ambiguity — both fields required on either branch; on branch B the month is shape-checked then discarded — `routes/dorders.py:96-97`
- §3.9 settlement variant — insert — ambiguity — an `EXECUTED` order with a null `pinned_decimal` (reachable: `SENT` → §3.6 dispute → forced `EXECUTED` by release) reads the pinned decimal as 0.00000000 — `routes/dorders.py:176`
- §3.9 audit variant — insert — ambiguity — a failed live re-evaluation yields `audit_decimal` 0.00000000 instead of failing the report; also named the previously unnamed field `audit_net_amount` — `routes/dorders.py:182-190`, `serializers.py:235`
- §3.9 suspense figures — insert — ambiguity — a read-triggered refresh is not a mutation: figures change but `updated_at`/`version` do not — `serializers.py:278-279` (no `touch`)
- §3.9 escheat — insert — ambiguity — `escheat_state_code` is any required non-empty string, not validated against the four state codes; `months_held` is recomputed in-request *before* the dormancy gate; the parent order's `cumulative_variance_amount`/`paid_net_total` and the held lines' `VARIANCE_HELD` status are untouched; those same lines re-enter `accrued_amount` when the row reopens — `routes/suspense.py:62-83`

Hand-offs:
- **(a) resolved** — `correct_order` → `compute_expected_decimal` → `select_allocation` genuinely runs all three failure modes, so §3.8's "the same three failure modes" is correct and §2.10 rung 44 was the wrong side. Rung 44 now reads "Guards issuing a division order and correcting one", with the unreachability argument recorded and verified (allocation rows are never deleted; `mineral_interests.tract_id` is write-once).
- **(b) confirmed accurate** — `serializers.refresh_suspense` returns early unless `suspense_status == "ACCRUING"`, and `suspense_out` is the only refresh path on reads (`routes/suspense.py:23,38`). Two corrections layered on: the figure count is five, not four, and a read's refresh does not bump `version`.

Final integrity check — PASS: §1–§5 present; 28 headings; endpoint table 59 rows; error table 59 rows / 59 distinct `ERR_` ids, set-equal to `errors.py::ERROR_STATUS` (59 keys) with zero status-code mismatches; final line exactly ``| `ERR_CORRECTED_DECIMAL_MISMATCH` | 422 |``; no truncation (last non-empty line of all 22 subsections and both tables ends in a complete punctuated sentence/row); 486 lines / 119,051 bytes.

### Orchestrator verification of Step 9

- `PRD.md` 484 lines / 101,076 B · `PRD_FINALIZED.md` 484 lines / 101,345 B · `PRD_COMPLETED.md` 486 lines / 119,051 B.
- `cmp PRD_FINALIZED.md PRD_COMPLETED.md` → differs (the byte-identical-copy failure mode did NOT occur); `diff` reports 94 changed lines.
- Independently re-counted: 28 headings, §4 table 61 pipe-rows (header + separator + 59 endpoints), 59 `ERR_` rows in §5, file ends on the `ERR_CORRECTED_DECIMAL_MISMATCH | 422` row.
- Confirmed no file under `test_suite/`, `test_helpers/`, or `workspace/implementation/` was modified after the 08:26 green sweep, so the 8×134/134 result remains valid for the shipped artifacts (Steps 8 and 9 edited only `workspace/PRD_*.md`).

## Pipeline complete — 2026-09-04T09:25:00.000Z

All nine steps finished. Final artifacts: SCAFFOLD.yaml + both design indices, `test_helpers/` (9 files / 1,770 lines), `test_suite/` (23 files / 134 tests), `workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md}`, `workspace/implementation/` (3,157 lines Python/Flask, 59 endpoints) and `workspace/implementation/results.{1..8}.json` all at 134/134.
