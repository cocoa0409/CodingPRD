# Worklog — task_0838_recycling_mrf_settlement

## Step 1: Create task directory — 2026-07-12T01:20:00.000Z

Task directory tasks/task_0838_recycling_mrf_settlement pre-created by user; used verbatim, skipped ./tasks scan + auto-numbering. workspace/ present.

## Step 2: Generate scaffold — 2026-07-12T01:46:00.000Z

All three artifacts generated and pass the linter cleanly. Summary for `task_0838_recycling_mrf_settlement`:

Deliverables (all under tasks/task_0838_recycling_mrf_settlement/):
- SCAFFOLD.yaml — §1.0–§1.7 (no design keys)
- SCAFFOLD_DIFFICULTY_DESIGN.yaml — §1.8, single top-level key
- SCAFFOLD_CORNER_DESIGN.yaml — §1.9, single top-level key

Design at a glance (Expert):
- Archetype: ledger reconciliation × pricing engine; flat topology (0% in examples, prioritized); cyclic state machines; peer_roles; layers = dual-variant calc, derived-field reconciliation, rate/threshold triggers, optimistic concurrency.
- 10 entities: Municipality, Mill, CommodityIndex, SortLine, DowntimeEvent, InboundLoad, Bale, MillShipment, MunicipalStatement, RevenueSharePosting (append-only, common_fields:false).
- 37 endpoints (incl. POST /_clock/set_current_utc with mandated 2026-03-01T00:00:00Z default); every FK reverse-reachable via filtered-list GETs.
- 5 state machines: InboundLoad (AUDITED↔PENDING_REAUDIT cycle), MillShipment (SETTLED↔DISPUTED cycle), Bale, CommodityIndex, MunicipalStatement.
- 8 calculations incl. dual-variant contamination adjustment (provisional/final) and bale valuation (provisional/final), pinned round-per-bale-then-sum settlement, freight waterfall, revenue share, statement totals, throughput, mass balance.
- 1 concurrency rule: OCC create-with-supersede on Municipality.version (statement create) — passes §1.2.1 serial-observability filter; no forbidden race vocabulary.
- 35 errors, 10 validation priority bands, 5 roles (4 opaque operators + entity-backed Municipality).

Test design:
- §1.8: 9 Difficulty Rules × 2 = 18 instances, each with executable setup_api_calls→trigger→assert chain and literal expected values.
- §1.9: 28 active corner instances + 7 excluded_because stubs across all nine claim-extraction sections.

Verification: scaffold_lint.py clean — §1.5 endpoints 37, §1.1 entities 10, §1.8 instances 18, §1.9 instances 28, calls scanned 334.
Note: endpoint count (37) and error count (35) run slightly above nominal Expert bands, driven by linter's hard FK-reverse-reachability requirement across 8 FK edges plus broad multi-workflow scenario.
All three files safe_load OK (orchestrator verified).

## Step 3: Copy shared files — 2026-07-12T01:47:00.000Z

Copied ./INSTRUCTION.md → workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-07-12T01:52:00.000Z

PRD generated at workspace/PRD.md (270 lines). Recycling MRF & Commodity Settlement (Expert, ledger-reconciliation + pricing-engine archetype).

Structure: 5 top-level sections. §2 (Global Specs) 10 subsections (RBAC, response envelope, pagination + 7 domain cross-cutting: common properties/versioning, monetary+mass precision, municipal revenue ledger, statement OCC, resource resolution/filtered retrieval/throughput, logical clock+index-window selection, validation ordering). §3 (Business Logic) 8 subsections by lifecycle.

Coverage: 37 endpoints in §4 table (matches scaffold), 35 error codes in §5 table (matches scaffold); every error id also in §2/§3 prose.

Hard contracts all PASS: field coverage (all entity fields + endpoint-only inputs to_iso8601, bale_id, expected_municipality_version, pct sub-key verbatim in backticks); rule coverage (6 state machines, both provisional/final calc variants, freight allocation, round-per-bale-then-sum settlement, revenue-share posting+reversal, statement totals, throughput+mass-balance, OCC rule w/ ERR_STALE_MUNICIPALITY_VERSION/412, priority-1-10 validation ordering); §3 path purity (no slash-paths/bare HTTP methods).

Notable: design files withheld (not opened). RevenueSharePosting (common_fields:false) documented as id+created_at only. Boundaries preserved: contamination thresholds inclusive both sides (5.0→rebate, 12.0→zero-point penalty); half-open index/period windows vs closed downtime intervals; reject threshold strict below 40 percent. Endpoint params deliberately scattered.

## Step 5: Generate unit tests — 2026-07-12T02:05:00.000Z

test_helpers/ (9 files): types.py (11 entity TypedDicts + 11 enums; RevenueSharePosting omits updated_at/version per common_fields:false), api_client.py (38 endpoint methods), api_errors.py (35 error IDs + HTTP-status map), assertions.py, factories.py, constants.py, test_users.py (4 opaque operational roles + entity-backed Municipality builder), fixtures.py (composite tiers: setup_audited_load, setup_closed_load_with_bale, setup_shipped_single_bale, setup_settled_single_bale, setup_two_window_shipped_bale, statement helper), __init__.py barrel.

test_suite/ (conftest + 11 test files, 65 tests):
- Queue A (Difficulty): 36 tests — all 18 instances across 9 rules, each 2 tests (primary + PRD-covered companion).
- Queue B (Corner): 29 tests — all 28 non-stub instances covered (≥1 each; corner_create_municipality_success got 2). 7 excluded_because stubs not translated.

Instances skipped: 0. Every non-stub instance passed the PRD-first two-condition filter. Numeric literals copied from design YAML and independently recomputed against PRD formulas.

Verification: all 20 files byte-compile; barrel imports; pytest --collect-only yields 65 tests no errors; ~80 citation substrings grep-confirmed against PRD.md. Every docstring ends with exactly one Design: tag. No skip/xfail.

## Step 6: Generate implementation — 2026-07-12T02:05:00.000Z

Files (workspace/implementation/): app.py (~800 lines single-file), requirements.txt (Flask 3.0.3), start.sh (guarded-install foreground, exec python3 app.py, reads $PORT, binds 0.0.0.0).

Endpoints: 37 (all from table). Orchestrator verified route count == 37 == scaffold endpoints; app.py py_compile OK.

Notable decisions:
- In-memory only: module-level dicts wiped every boot via _reset_state(); no seeding. Logical clock defaults 2026-03-01T00:00:00Z.
- Money: cents arithmetic Decimal ROUND_HALF_UP; tons 3 decimals, throughput 2. Verified provisional/final bale value, contamination rebate/penalty, per-bale round-then-sum settlement, revenue share, REVERSAL netting to 0 on dispute.
- Ledger cascade: create_posting updates 4 municipality counters, re-derives balance_cents, bumps version per posting. Close posts REBATE/PENALTY only when adjustment≠0.
- Derived-field-as-mutation: recompute SortLine throughput, load mass balance, shipment tons each touch() resource (version++/updated_at++).
- Validation ordering follows PRD §2.10 priority. Where §3.7 prose and §2.10 disagreed on fine-grained 422 ordering (bale-assign: load-closed vs commodity-mismatch), followed §2.10 (referential before safety). FLAGGED for Step 7/8/9 review.
- OCC: expected_municipality_version checked after existence (412 ERR_STALE_MUNICIPALITY_VERSION); statement create supersedes prior OPEN then bumps version.
- Index selection: half-open [start,end) window matching, adjacency-supersede on publish.
- Response envelope, pagination (clamped 1-100), per-resource 404 IDs match scaffold/PRD.
- Assumption flagged: at bale creation if no PUBLISHED index in force, snapshot+provisional value default to 0 (no error defined; tests expected to publish index first).

## Step 7: Test and iterate — 2026-07-12T02:12:00.000Z

All 8 rounds green (65/65). Ran as 2 waves of 4 concurrent rounds (host self-saturation avoidance). Orchestrator confirmed all 8 results files 65/65.

Iterations run: 2 (baseline sweep exposing 2 stable failures; one fix batch; confirming sweep).

Tests deleted: None. No test failed PRD coverage or unique-derivability.

Fixes applied to test_helpers/: None. Shared fixtures (setup_settled_single_bale → setup_closed_load_with_bale) construct a PRD-legal flow.

Fixes applied to implementation/: None. Implementation was already PRD-faithful.

Fixes applied to test_suite/ (test_05_shipment_settlement.py): Two assertion constants omitted a PRD-required side effect. Corrected to PRD-derived values (not weakened — still exact equality):
- test_settle_posts_revenue_share_to_balance: balance_cents 42600 → 45600, added revenue_share_accrued_cents == 42600 check. Single-bale load closes residual 0 → 0% contamination → PRD §3.5 (line 156) mandates clean REBATE net_tons(10)×300 = 3000, and PRD §2.6 derives balance = revenue_share_accrued(42600) + lifetime_rebate(3000) − lifetime_penalty(0) = 45600.
- test_dispute_reverses_revenue_share_to_zero: balance_cents 0 → 3000 (kept revenue_share_accrued_cents == 0). Per PRD §3.7 dispute reverses only the REVENUE_SHARE posting; the clean-close REBATE (3000) is not reversed, so balance restored to pre-settlement 3000.

Root cause: fixture setup_settled_single_bale forces residual=0 (bale consumes entire load net), so a 3000 REBATE is PRD-mandated. The other two balance tests use setup_two_window_shipped_bale (residual 2.0/net 20 = 10% → adjustment exactly 0), avoiding the rebate; author forgot it in these two.

Final: 65/65 passed in all 8 rounds. All green.

## Step 8: Finalize PRD — 2026-07-12T02:18:00.000Z

PRD_FINALIZED.md created as exact copy of PRD.md; after verifying every step_7_diff behavior against implementation/, no edits warranted. PRD.md 270 / PRD_FINALIZED.md 270, 0-line delta, byte-identical (orchestrator confirmed diff -q).

Zero-edit justification: step_7_diff had 0 impl fixes, 0 deletions, 0 test_helpers fixes — only two test_05 assertion constants corrected TO match PRD. All three hinge behaviors already verbatim + unambiguous in PRD.md and impl matches exactly:
- §3.5 clean-close REBATE: "If contamination is at most the clean threshold of 5.0 percent...adjustment is a positive amount equal to net_tons multiplied by 300 cents per ton, rounded half up" + close cascade posts REBATE when amount positive. Impl close_load app.py:790-799 + contamination_adjustment app.py:323-328. Consistent.
- §2.6 balance: "balance_cents is derived as revenue_share_accrued_cents plus lifetime_rebate_cents minus lifetime_penalty_cents". Impl recompute_balance app.py:354-357 exact. Consistent.
- §3.7 selective dispute reversal: "For every REVENUE_SHARE posting...a REVERSAL posting is written whose amount_cents is the negation" — only REVENUE_SHARE, so clean-close REBATE survives dispute. Impl dispute_shipment app.py:1042-1049 filters strictly on REVENUE_SHARE. Consistent.

Per-edit search log: zero edits; NO-NEW-MISMATCH enumeration covered contamination-adjustment posting, balance projection (counters, municipality init, statement finalize), dispute reversal scope — all consistent. PRD_FINALIZED.md identical to PRD.md, a valid outcome.

## Step 9: Complete PRD — 2026-07-12T02:22:00.000Z

PRD_COMPLETED.md created from PRD_FINALIZED.md; walked implementation/app.py (1182 lines) end-to-end. Source 270 lines / 39,231 chars → output 270 lines / 40,105 chars (+874 chars, all in-paragraph inserts). Ambiguity-pins: 3, Mismatch-revisions: 1.

Changes:
- §3.7 (bale-assign) — revise — mismatch — Reordered the four assign checks so source-load-CLOSED (ERR_BALE_LOAD_NOT_CLOSED, priority 6) precedes commodity-match (ERR_COMMODITY_MISMATCH, priority 7), matching §2.10; resolves the Step-6 self-flagged §3.7-vs-§2.10 conflict. impl app.py:963-969
- §3.6 (Baling) — insert — ambiguity — Pinned that when no PUBLISHED index is in force for the commodity at bale creation, index_price_snapshot_cents and provisional_value_cents both default to 0 (valuation skipped). impl app.py:836-838
- §3.5 (Closing) — insert — ambiguity — Pinned that a final adjustment of exactly 0 (neutral 5.0–12.0 band) creates no RevenueSharePosting and leaves municipality counters, balance_cents, version unchanged. impl app.py:796-801
- §3.7 (Disputing) — insert — ambiguity — Pinned that a disputed bale's freight_share_cents is left unchanged (only final_value_cents and shipment gross_settlement_cents reset to 0). impl app.py:1050-1053

Edge cases with no observable/test surface (net_tons=0 close division guard, total_net=0 freight guard, negative-offset pagination clamp) left unpinned to keep patch minimal. No new sections/paragraphs; nothing invented.

Steps 8/9 touched only PRD docs (not implementation/ or tests) — the 65/65-across-8-rounds pass state stands. PIPELINE COMPLETE.
