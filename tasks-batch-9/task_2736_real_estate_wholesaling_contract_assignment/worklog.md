# Worklog — task_2736_real_estate_wholesaling_contract_assignment

## Step 1: Create task directory — 2026-09-04T13:43:26.313Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2736_real_estate_wholesaling_contract_assignment` and its `workspace/` subdirectory. Index 2736 was pre-assigned by the invoking pipeline; no index scan was performed (other pipelines run concurrently on this host).

## Step 2: Generate scaffold (subagent) — 2026-09-04T15:04:39.554Z

All three scaffold artifacts are complete, parse as YAML, and pass the scaffold linter on the first run.

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2736_real_estate_wholesaling_contract_assignment/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2736_real_estate_wholesaling_contract_assignment/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2736_real_estate_wholesaling_contract_assignment/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    60
  §1.1 entities declared:     14
  §1.8 instances scanned:     18
  §1.9 instances scanned:     42
  Calls scanned (§1.8+§1.9):  549

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Files

| Path | Lines | Size |
|---|---|---|
| `SCAFFOLD.yaml` | 3259 | 154,208 B |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2117 | 132,229 B |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 2469 | 149,988 B |

`SCAFFOLD.yaml` top-level keys are `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, resource_temporal_overlap_rules, validations, endpoints, errors, roles` — neither `scaffold_difficulty_design` nor `scaffold_corner_design` appears. Each design file has exactly one top-level key.

## Domain model shape

- **14 entities**: Wholesaler, MarketingCampaign, SellerLead, DealAnalysis, DisclosureAcknowledgement (immutable, `common_fields: false`), PurchaseContract, EarnestMoneyDeposit, CashBuyer, ProofOfFunds, AssignmentOffer, AssignmentAgreement, TitleOrder, ComplianceReview, DisputeCase. Flat topology; parents on DisclosureAcknowledgement/EarnestMoneyDeposit (PurchaseContract) and ProofOfFunds (CashBuyer).
- **60 endpoints** plus the logical clock; **12 state-machine dimensions** including PurchaseContract's three parallel dimensions (contract_status / assignment_status / structure_election); **8 calculations**; **2 concurrency rules**; **43 validations**; **55 errors**.
- **6 roles** with segregation of duties: Wholesaler (`entity_backed:Wholesaler`), Seller (`entity_backed:SellerLead`), CashBuyer (`entity_backed:CashBuyer`), TitleAgent, ComplianceOfficer, PlatformAdmin (opaque). Dual control on title funding, segregation on compliance adjudication.
- Profile: compliance_audit / multi_party_negotiation, cyclic state machines, `consistency_model: immediate`, layers `optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers`.

## Instance counts

- **§1.8 — 18 instances**, 2 per each of the nine Difficulty Rules (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).
- **§1.9 — 48 instances = 42 full test recipes + 6 `excluded_because` stubs**, across all nine claim-extraction sections: entities 12, state_machines 7, calculations 5 (1 stub), validations 4, endpoints 4, errors 5 (2 stubs), rbac 4, cross_cutting_layers 6 (3 stubs), consistency_model 1. All 48 §1.9 names plus the 18 §1.8 names are unique across the union, and every cited `difficulty_instance` resolves to a real §1.8 instance.

Notable corner coverage: GLA-band comparable exclusion (ARV 30,000,000 vs the 32,500,000 decoy), `equity_pct` 4-dp quantisation (0.6667), tier-1 minimum-fee floor on the double-close schedule (714,700 / 25,000 / 739,700), the tier-2 schedule (29,609,000 / 666,203 / 30,275,203), the equity-skimming floor at exactly 18,200,000 both sides, the priority-28-over-priority-40 conflict, both declared OCC rules, and dual-control/segregation denials.

## Step 3: Copy shared files — 2026-09-04T15:05:00.470Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 B).

## Step 4: Generate PRD (subagent) — 2026-09-04T15:20:15.419Z

The PRD is complete and non-truncated.

## What was produced

`workspace/PRD.md` — **489 lines, 103,040 bytes**, ending at a genuine section boundary (the final row of the §5 error table).

Exact last 3 lines:
```
| `ERR_OFFER_BELOW_CONTRACT_PRICE` | 422 |
| `ERR_INSUFFICIENT_VERIFIED_FUNDS` | 422 |
| `ERR_ASSIGNMENT_FEE_CAP_EXCEEDED` | 422 |
```

No audit footer, no contract-report block in the file. Written via one `Write` plus four heredoc appends, so the 64k output cap was never approached.

## Structure

§1 Introduction (3 paragraphs), §2 with 12 subsections (2.1 Principals/RBAC, 2.2 verbatim envelope, 2.3 Pagination, 2.4 Identity & Version, 2.5 Logical Clock, 2.6 Rounding, 2.7 OCC, 2.8 the 43-rank rejection ladder, 2.9 Hold Cascade, 2.10 Segregation/Dual Control, 2.11 Conservation Invariants, 2.12 Interval Semantics), §3 with 9 lifecycle subsections, §4 (4-column, 60 rows), §5 (2-column, 55 rows).

## Hard Contract Reports

```
Field coverage check:
- entities[].fields: 134 required, 134 present, 0 missing   (incl. comparables/repair_scope_items element members)
- endpoints[].request_body: 73 required, 73 present, 0 missing
- endpoints[].query_params: 25 required, 25 present, 0 missing
- endpoints[].path_params: 14 required, 14 present, 0 missing
Status: PASS
```
Verified twice — once with token-split matching, once with strict exact-standalone-backtick matching (0 missing under the stricter test).

```
Rule coverage check:
- validations[] with priority: 43 checked, 43 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_purchase_contract_version / expected_seller_lead_version + error_id + 412 all named), 0 missing
- state_machines[].transitions: 47 checked, 47 fully expressed, 0 missing
- calculations[]: 8 checked, 8 fully expressed, 0 missing
- validations[] conditions: 43 checked, 43 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 60 endpoints + 2 overlap rules checked, all expressed, 0 missing
- entities[].fields[] structured content: 14 entities checked, reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked (3 →ACCEPTED edges, 2 →CANCELLED cascade edges, 2 →PUBLISHED edges, 3 →ARCHIVED edges, 2 valuation variants, 2 screening variants), 6 with equal prose density, 0 asymmetric
Status: PASS
```
All 55 `errors[].id`, all state values, and all enum values appear verbatim in backticks (mechanically verified: 0 missing).

```
Path purity check (§3 only):
- backtick tokens scanned: 795
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Also verified: §2.2 is byte-identical to `section-2.2-response-structure.md`; zero fuzzy/approximating words anywhere in the document.

## Notable fidelity decisions

- The 43-rule precedence ladder lives in §2.8 with each rule's error ID, HTTP status and full `applies_to` scope stated in **capability language, never paths** — so Contract 2 category 4 is satisfied without leaking the API surface into the narrative, and §4 stays the only place paths appear.
- Rank 12's "residual guard" semantics (specific rules at 13–22 win where they apply) is stated explicitly, since naive ascending evaluation would report `ERR_INVALID_STATE` where the scaffold wants a specific code.
- The two interval-overlap rules are contrasted side by side in §2.12 with an explicit warning that sharing one comparison routine breaks one of them (closed+adjacency-collides for property vs. half-open+48h-buffer+capacity for funding windows).
- The mandatory evaluation orders that produce off-by-one-cent divergence — three independently rounded settlement components, sum-then-multiply-then-round-once for the repair contingency, tier selection from the grossed-up base rather than the raw price, minimum-fee floor applied after rounding — are each called out as non-negotiable rather than merely described.
- `DisclosureAcknowledgement`'s absence of `updated_at` and `version` is stated explicitly as the single exception to the common-fields rule.

**Orchestrator truncation verification (independent):** `wc -l -c` = 489 lines / 103040 bytes; `tail` confirms the file ends with a complete `| \`ERR_ASSIGNMENT_FEE_CAP_EXCEEDED\` | 422 |` table row; `grep '^#'` confirms all of §1–§5 present with §5 as the final heading. Not truncated.

## Step 5: Generate unit tests (subagent) — 2026-09-04T16:39:35.149Z

Generation is complete and verified. Both output directories are at the task root; nothing was written under `workspace/`, and `worklog.md` was not touched.

## Output

`test_helpers/` — 3636 lines
```
 221  __init__.py        (facade re-exports)
 498  api_client.py      (ApiClient + canonical_instant/instants_equal)
 153  api_errors.py      (ApiErrorId, ERROR_HTTP_STATUS)
 872  assertions.py      (entity asserters + PRD arithmetic oracles)
 165  constants.py       (thresholds, tiers, buffers, page limits)
 466  factories.py       (payload builders; all money as Python ints)
 898  fixtures.py        (Scenario + build_* ladders and endpoint verbs)
 106  test_users.py      (role headers + fixed X-User-IDs)
 457  types.py           (all enum literal sets)
```

`test_suite/` — 5358 lines, 77 tests
```
  23  conftest.py
 475  test_01_entity_lifecycle.py             11 tests
 320  test_02_state_machines.py                7
 245  test_03_calculations.py                  4
 221  test_04_validations.py                   4
 295  test_05_endpoints.py                     4
 211  test_06_errors.py                        3
 239  test_07_rbac.py                          4
 281  test_08_cross_cutting.py                 4
 309  test_09_dual_variant.py                  4
 265  test_10_combinatorial_formula.py         4
 299  test_11_non_linear_state_machine.py      4
 306  test_12_transitive_cascade.py            4
 258  test_13_priority_conflicts.py            4
 286  test_14_boundary_precision.py            4
 316  test_15_cross_entity_state_dependency.py 4
 363  test_16_resource_temporal_overlap.py     4
 446  test_17_compensating_invariant.py        4
```

## Verification results

- `python3 -m compileall test_helpers test_suite` — clean (pycache then removed).
- `pyflakes` — clean on all 17 test modules and all helper modules except the expected unused-import notices on `test_helpers/__init__.py`, which is a deliberate re-export facade.
- Design tags: 77 tests, 77 tags, one per test, `tests == tags` in every file. 41 corner tags (41 distinct instances, each used once) + 36 difficulty tags (18 distinct instances × 2 tests). Every tagged instance name matches exactly one `name:` in its source yaml (no missing, no duplicate). All 9 difficulty `rule_id`s carry 4 tests each.
- No occurrence of the word "scaffold" anywhere in either directory.

## Deliberate gaps (PRD-first filter)

- Corner `proof_of_funds_with_unknown_cash_buyer_returns_not_found` skipped; the four corner stub sections (1 calculations, 2 errors, 3 cross_cutting_layers) yielded no tests by design.
- `transitive_cascade`'s `TERMINATED_UPSTREAM`-after-cancel agreement hop is unreachable — the PRD drives the offer to `CONSUMED` on execution — so it stays a gap.
- Two design assertions dropped as not uniquely derivable from the PRD: `buffered_window_end_at` on an `ASSIGNMENT`-structured title order (PRD derives it only for `DOUBLE_CLOSE`), and `adjudicated_at` on `DisputeCase` (that field exists only on `ComplianceReview`). Both parent instances are still covered.

## Step 6: Generate implementation (subagent) — 2026-09-04T15:59:59.222Z

The implementation is complete, compiling, and smoke-verified end to end.

## Files — `workspace/implementation/`

| file | lines | role |
|---|---|---|
| `common.py` | 443 | 55-code→HTTP table, `ApiError`/`fail`, logical clock + `iso_ms` (exactly 3 fractional digits), in-memory `Store`/`db`, envelope builders, auth (`X-User-Role`/`X-User-ID`), body validators, pagination/sorting/filtering |
| `calc.py` | 283 | all 8 deterministic calculations in `Decimal`/integer cents: ARV (conservative median / aggressive recency-weighted), repairs, MAO, seller equity + tier, equity floor, assignment-fee settlement split, double-close funding schedule, fee caps, escrow disposition, dispute award |
| `services.py` | 532 | graph navigation, `set_fields` (version bumps only on real change), buyer-capital + wholesaler recomputation, compliance-hold cascade, cancellation cascade, both interval semantics, shared guards |
| `routes_a.py` | 285 | wholesalers, marketing campaigns, seller leads (12 endpoints) |
| `routes_b.py` | 488 | deal analyses, purchase contracts, disclosure acks, earnest-money deposits (19) |
| `routes_c.py` | 392 | cash buyers, proof of funds, assignment-offer negotiation (16) |
| `routes_d.py` | 504 | assignment agreements, title orders, compliance reviews, dispute cases, `_clock/set_current_utc` (18) |
| `app.py` | 72 | Flask factory, 4 route registrations, `ApiError`/HTTPException/404/405/500 handlers emitting the error envelope, `PORT` env (default 10000) |
| `start.sh` | 13 | `set -euo pipefail`, cd to script dir, flask presence check, `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=2.0` |

**3013 lines total. 60 endpoints registered** — verified by enumerating `app.url_map`, matching the SCAFFOLD count exactly. All 10 files pass `python3 -m py_compile`.

## Smoke results (port 52101/52103; only my own PIDs killed, never a pattern kill)
Two scripted scenarios, both **ALL PASS** (~90 assertions):
- **Happy path:** wholesaler → campaign → publish → lead → protection screen (`net_equity 6690000`, `equity_pct 0.2091`, STANDARD) → analysis (3 qualifying comps, ARV 32500000, MAO 20430000) → contract (deadline auto-set to `closing_start − 48h`) → disclosure ack → sign (HELD deposit auto-created) → elect ASSIGNMENT → buyer + POF verify (capital 40000000/0/40000000, PRIORITY) → offer → counter → revise → accept (fee 1400000) → agreement → settle (45500 / 10500 / 21700 / net 1322300) → title order → clear-to-fund → fund-and-close (contract CLOSED, deposit APPLIED_AT_CLOSING, `executed_assignment_count` 1) → 2 adverse reviews → hold true, campaign SUSPENDED, subsequent lead creation blocked → clock advance.
- **Alternate path:** AGGRESSIVE valuation, occupancy conflict 409, assignment-without-rights rejection, DOUBLE_CLOSE election (funding 25525000 + 574313 = 26099313), buffered window `+48h`, funding-window capacity conflict 409, premature forfeit 409 then forfeit, dispute fork-join (`EVIDENCE_PARTIAL`→`EVIDENCE_COMPLETE`), SPLIT_50_50 award (400000/400000, escrow conserved at 800000 across 2 events), wholesaler-cancel time-box 409 vs seller cancel 200 with full cascade (title order CANCELLED, lead back to SCREENED).
- Cross-cutting probes: OCC 412 on both version fields, 401 missing/unknown role, 401 missing `X-User-ID` on POST, 403 wrong role, 404 unknown id, 400 `limit=0`, envelope shape (`req_` + 20 alnum id, 3-digit-ms timestamp, `limit/offset/total_count/has_more`).
- **Fresh-boot isolation confirmed:** after kill + relaunch, all 14 collections report `total_count 0` and the clock is back at `2026-08-01T00:00:00.000Z`. No SQLite/JSON/cache file is ever written (`find` for non-source files returns nothing).

Two notes for the record: ports 48736 and 51736 were already occupied by other pipelines, so I probed for a free port (52101/52103) rather than disturbing anything. And where PRD §3.x prose orders guards differently from the §2.8 ladder, I followed the ladder — §2.8's preamble ("evaluated in strictly ascending rank; the first violation found is the one reported") is the explicit global authority, so e.g. contract creation reports `ERR_LEAD_NOT_SCREENED` (15) ahead of `ERR_WHOLESALER_COMPLIANCE_HOLD` (23), and dispute adjudication reports `ERR_DEPOSIT_NOT_HELD` (21) ahead of `ERR_EVIDENCE_INCOMPLETE` (22).

**Orchestrator note on Steps 5/6 launch:** the two agents were launched in immediate succession rather than in a single assistant message. Physical isolation was preserved by explicit prohibition instead: the impl generator was forbidden from reading `test_helpers/`, `test_suite/`, and both design YAMLs, and the test generator was forbidden from reading `workspace/implementation/`. Both directories were verified to be at the task root, with no strays under `workspace/`.

## Step 7: Run tests and iterate (subagent) — 2026-09-04T16:51:17.786Z

The sweep came back clean on the first iteration, and I verified the artifacts are genuine rather than vacuous before exiting.

## Summary

**Iterations run:** 1 (the first 8-round parallel sweep passed clean, so no fix/rerun cycle was needed).

**Tests deleted:** None. No test failed in any of the 8 rounds, so the STEP 1 coverage / unique-derivability protocol was never triggered — there was no failing test to adjudicate for PRD silence.

**Fixes applied to `test_helpers/`:** None required.

**Fixes applied to `implementation/`:** None required.

**Validation that this is not a vacuous green:**
- `test_suite/` declares exactly 77 test methods (`grep -rhE "^\s+def test_"`), and every round's `results.$i.json` contains 77 unique `(file, name)` entries — full collection, nothing deselected.
- Zero `pytest.mark.skip` / `xfail` markers anywhere in `test_suite/` or `test_helpers/`.
- 192 assertion calls across the suite, asserting 24 distinct exact `error_id` values — including the hard corner rules (`ERR_STALE_CONTRACT_VERSION`, `ERR_STALE_LEAD_VERSION`, `ERR_DUAL_CONTROL_REQUIRED`, `ERR_SEGREGATION_OF_DUTIES`, `ERR_PROPERTY_OCCUPANCY_CONFLICT`, `ERR_FUNDING_WINDOW_CONFLICT`, `ERR_ASSIGNMENT_FEE_CAP_EXCEEDED`), so precedence and boundary behavior are genuinely exercised.
- Per-round wall time was 176–182s with ~2.3–2.6s per test, consistent with a real `--isolation per-test-server` reboot before each of the 77 tests.
- No stray `test_suite/` or `test_helpers/` directories under `workspace/`; `workspace/implementation/` holds only the 8 source modules plus `start.sh`. Storage is in-memory only (`common.py` `Store`, empty on every boot, nothing seeded). I did not read or write `worklog.md`.

**Final confirmation line:**
- results.1.json — 77/77
- results.2.json — 77/77
- results.3.json — 77/77
- results.4.json — 77/77
- results.5.json — 77/77
- results.6.json — 77/77
- results.7.json — 77/77
- results.8.json — 77/77

All 8 parallel rounds: `passed == total == 77`, `failed == 0`, `errors == 0`, `skipped == 0`. No flakiness surfaced across the sweep.

**Orchestrator independent verification (per standing check that a Step 7 agent can claim a clean sweep with no artifacts on disk):** all 8 `workspace/implementation/results.$i.json` exist on disk (~25.3 KB each, written 16:44), and parsing each confirms `passed=77 total=77 failed=0 errors=0 skipped=0` with 77 unique `(file, name)` test entries per round. Independent `grep` of `test_suite/` counts 77 `def test_` methods (matches `total`), and `grep` for `mark.skip|mark.xfail` across `test_suite/` and `test_helpers/` returns 0 hits. The green is genuine.

## Step 8: Finalize PRD — SKIPPED — 2026-09-04T16:51:28.190Z

Skip condition from the skill applies exactly: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline. `PRD.md` therefore already determined every behavior the test suite exercised, so there is no Step 7 diff for Step 8 to target and no subagent was spawned. No `PRD_FINALIZED.md` is produced; Step 9 consequently starts from `PRD.md`.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch (subagents) — 2026-09-04T17:17:03.964Z

**Orchestrator design decision.** Step 9 was executed as **three sequential module-partitioned passes over one shared `workspace/PRD_COMPLETED.md`** rather than as a single whole-implementation scan. Rationale: a single agent asked to hold the entire 3013-line implementation plus the 489-line / 103 KB PRD reliably runs out of working context and no-ops, leaving `PRD_COMPLETED.md` byte-identical to its source — which is indistinguishable from "the scan found nothing" but is in fact a silent failure. Partitioning by implementation module keeps each pass's read set small enough to audit exhaustively. Pass 1 performed the `cp` that creates the file; passes 2 and 3 were explicitly forbidden from re-copying it (a re-copy would erase prior passes' edits) and edited it in place with the Edit tool only. Source was `PRD.md`, since Step 8 was skipped and no `PRD_FINALIZED.md` exists.

Partition: pass 1 = `common.py` + `app.py` + `calc.py`; pass 2 = `services.py` + `routes_a.py` + `routes_b.py`; pass 3 = `routes_c.py` + `routes_d.py`. Union covers all 8 implementation modules exactly once.

### Pass 1 of 3 — common.py, app.py, calc.py

Line counts: `PRD.md` 489 lines / 103040 chars → `PRD_COMPLETED.md` 489 lines / 107703 chars. Char delta **+4663**; line count unchanged (all edits in-paragraph). 14 changes: **11 ambiguity-pins, 3 mismatch-revisions.** Truncation guard verified.

- §2 intro — insert — ambiguity — trailing slash accepted as equivalent to bare path; all state in process memory, every collection empty at boot and never seeded — `app.py:30`, `common.py:131-160`
- §2.1 — insert — ambiguity — `X-User-ID` required on every `POST` (clock setter included) and not required/ignored on every `GET` read and list; whitespace-only header counts as missing and the value is stripped before comparison or recording — `common.py:262-271`
- §2.2 (`api_request_id` bullet) — insert — ambiguity — `req_` followed by exactly twenty characters from `A`–`Z` and `0`–`9` — `common.py:191-195`
- §2.2 (`api_request_timestamp` bullet) — revise — **mismatch** — PRD §2.5 declared nothing reads the wall clock, but this field is stamped from the host clock and is unrelated to `current_utc` — `common.py:201`
- §2.2 (error envelope preamble) — revise — **mismatch** — envelope also covers the 5xx fault response, not 4xx only — `app.py:61-63`
- §2.3 — insert — ambiguity — an unparseable `limit`/`offset` (`10.5`, non-numeric) is `ERR_INVALID_REQUEST` checked *before* the range test; a parameter with an empty value takes its default — `common.py:402-419`
- §2.3 — insert — ambiguity — the `created_at` tiebreaker is a server-assigned strictly increasing creation sequence never exposed in responses; filters are exact case-sensitive matches applied before ordering; empty-valued and undocumented query params ignored — `common.py:422-440`
- §2.4 — insert — ambiguity — rendered form `YYYY-MM-DDTHH:MM:SS.mmmZ`, sub-millisecond precision truncated rather than rounded — `common.py:97-107`
- §2.5 — revise — **mismatch** — "nothing reads the wall clock" rescoped to business rules (envelope timestamp excepted); plus pins: clock response object carries `current_utc` as its sole member, a backwards `to_iso8601` is accepted, and body instants accept `Z`/`+00:00`/zone-less (read as UTC) while any non-zero offset reports `ERR_INVALID_REQUEST` — `common.py:110-125`, `common.py:201`
- §2.6 — insert — ambiguity — `equity_pct` serialises as a bare JSON number, so `0.3500` prints as `0.35` — `common.py:216-217`
- §2.8 rank 3 — insert — ambiguity — explicit JSON `null` counts as absent (required → 400, optional → default); integer fields reject booleans and fractional forms like `5.0`; string limits count characters with no trimming, so blanks satisfy non-empty; absent/empty body reads as `{}` while non-JSON or non-object bodies report 400 — `common.py:277-350`, `common.py:382-387`
- §3.4 — insert — ambiguity — `distance_miles` compared in exact decimal on the submitted value, no float tolerance — `calc.py:81`
- §3.9 — insert — ambiguity — under `SELLER_KEEPS_EARNEST_MONEY` the deposit's `status` also stays `FORFEITED_TO_SELLER` — `calc.py:266-268`
- §4 intro — insert — ambiguity — three responses outside the §5 catalogue: unrouted path → 404 `ERR_NOT_FOUND`, bad method → 405 `ERR_METHOD_NOT_ALLOWED`, unhandled fault → 500 `ERR_INTERNAL`, all in the §2.2 error envelope — `app.py:41-63`

Pass 1 notes: `calc.py` was already near-perfectly pinned — all eight calculations (ARV median ordering and even-count floor, 181-day recency weights, contingency-once repair rounding, MAO floor-then-subtract, both equity variants and tier thresholds, the 0.60 equity floor, the three separately-rounded settlement components, the gross-up-then-tier funding schedule with half-open tier edges, the 12/8/5 % floored fee cap with strictly-greater rejection, and all three dispute awards) matched PRD prose exactly, yielding only 2 findings. The bulk of the silence lived in `common.py`'s validation/serialization/pagination layer. Two deliberate non-pins: `app.py`'s `PORT` env default (10000) — the PRD has no hosting/deployment prose and pinning it would have required a new section; and the generic `HTTPException` fallback at `app.py:51-59`, which no route can reach (`get_json(force=True)` suppresses 415), left unpinned rather than documenting unreachable behavior.

### Pass 2 of 3 — services.py, routes_a.py, routes_b.py

Line counts: `PRD.md` 489 / 103040 → `PRD_COMPLETED.md` 489 / 111819. Total char-delta vs `PRD.md` **+8779**; delta attributable to pass 2 **+4116** (107703 → 111819). Line count unchanged. 18 changes: **10 ambiguity-pins, 8 mismatch-revisions.** All 14 pass-1 edits verified intact by marker grep (each present exactly once). Truncation guard verified.

- §2.4 — insert — ambiguity — a derived-value recomputation that moves nothing is not a mutation: `updated_at`/`version` unchanged; endpoint-own writes always count — `services.py:53-62`
- §2.9 — revise — **mismatch** — "each of those touched records has its version incremented" was unconditional; a lead whose `lead_gen_blocked` was already true is not rewritten at all — `services.py:279-299`
- §3.2 — insert — ambiguity — drafting a campaign is *not* ownership-checked; body `wholesaler_id` is resolved but never compared to `X-User-ID` — `routes_a.py:80-92`
- §3.2 — revise — **mismatch** — PRD said lead-recompute was an effect only re-publication has; impl runs it on both publish edges (vacuous on `DRAFT → PUBLISHED`) — `routes_a.py:163`
- §3.3 — revise — **mismatch** — `distress_flags` "holds distinct values" implied rejection; impl accepts and echoes duplicates verbatim (collapsed only when the screen counts), and caps no length — `routes_a.py:193-200`
- §3.3 — insert — ambiguity — recording a lead is likewise not ownership-checked — `routes_a.py:202-211`
- §3.3 — revise — ambiguity — protection screen is available only from `PROSPECT`/`SCREENED` (else `ERR_INVALID_STATE`), and the `lead_gen_blocked` precondition is checked *after* the compliance-hold guard and also reports `ERR_INVALID_STATE` — `routes_a.py:267-275`
- §3.4 — insert — ambiguity — both `comparables` and `repair_scope_items` are required (absent/`null`/non-array → `ERR_INVALID_REQUEST`); empty arrays accepted; 21st comparable rejected — `routes_b.py:29-34`
- §3.4 — insert — ambiguity — 41st repair item reports `ERR_INVALID_REQUEST` — `routes_b.py:57-59`
- §3.4 — insert — ambiguity — the live-contract check sweeps all priors before any is superseded, so a rejection supersedes nothing — `routes_b.py:100-113`
- §3.4 — revise — **mismatch** — `qualifying_comp_count` is recomputed at finalization too, not only at creation — `routes_b.py:159-162`
- §3.5 — revise — **mismatch** — PRD prose said the compliance hold is "stopped first"; impl (and §2.8 ranks 15/16/23) puts `ERR_LEAD_NOT_SCREENED` then `ERR_DEAL_ANALYSIS_NOT_FINALIZED` *before* `ERR_WHOLESALER_COMPLIANCE_HOLD` — `routes_b.py:210-222`
- §3.5 — revise — **mismatch** — PRD said the acknowledged template "must equal" the wholesaler's current one; impl performs **no** validation at file time — the version only matters as a filter at signing — `routes_b.py:415` / `routes_b.py:300-304`
- §3.8 — insert — ambiguity — supplying `UNDECIDED`, or the election already carried, has no transition and reports `ERR_INVALID_STATE` — `routes_b.py:351-352`
- §3.8 — insert — ambiguity — the spread's "accepted offer" is any offer in `ACCEPTED` or `CONSUMED`, and the most recently accepted one wins — `services.py:144-154`
- §3.9 — insert — ambiguity — cancelling an already-terminal contract reports `ERR_INVALID_STATE`, not `ERR_CONTRACT_TERMINAL` — `routes_b.py:397-398`
- §3.9 — revise — **mismatch** — PRD said an unsigned cancellation returns the lead to `SCREENED` unconditionally; impl applies the same only-non-terminal-contract condition as the signed edges — `services.py:458-461`
- §3.9 — revise — **mismatch** — level three selects agreements by reachability from the contract, not "whose offer just lapsed" (an executed agreement's offer is `CONSUMED`, never lapsed) — `services.py:436-443`

Pass 2 notes: (a) `hold_cascade` guards on "`compliance_hold` is true after this adjudication" rather than a strict false→true transition, and `recompute_wholesaler` + `hold_cascade` run on `CLEAR` adjudications too — §2.9 was left as-is because both are provably unobservable (the adverse count is monotonic and publishing requires the hold to be false, so no `PUBLISHED` campaign can exist while on hold). (b) §3.9's forfeiture prose enumerates `ERR_DEPOSIT_NOT_HELD` before `ERR_CONTRACT_NOT_SIGNED` while impl checks signed first; left as-is since §2.8's ranks 17/21 already pin the reporting order authoritatively and the §3.9 sentence is not phrased as an ordering.

### Pass 3 of 3 — routes_c.py, routes_d.py

Line counts: `PRD.md` 489 / 103040 → `PRD_COMPLETED.md` 489 / 121233. Total char-delta vs `PRD.md` **+18193**; delta attributable to pass 3 **+9414** (111819 → 121233). Line count unchanged. 26 changes: **18 ambiguity-pins, 8 mismatch-revisions.** Truncation guard intact; 5/5 spot-checked prior-pass edits still present.

- §3.6 — insert — ambiguity — cash-buyer creation is neither ownership-checked nor hold-gated — `routes_c.py:29-37`
- §3.6 — insert — ambiguity — proof `expires_at` need not be in the future at submission — `routes_c.py:77`
- §3.6 — insert/revise — **mismatch** — `verification_decision` is trimmed/upper-cased free text over 8 accepted tokens; override only `>= 0` and never compared to `stated_funds_cents`; `verification_note` validated then discarded — `routes_c.py:22-23,119-131,120-121`
- §3.6 — insert — **mismatch** — a rejection also stamps `verified_at`/`verified_by_user_id`; the expiry test runs on the approval path only — `routes_c.py:137-151`
- §3.7 — insert — ambiguity — bad-buyer supersede → `ERR_NOT_RESOURCE_OWNER`, bad-contract supersede → `ERR_INVALID_STATE` — `routes_c.py:180-197`
- §3.7 — insert — ambiguity — the two residual `ERR_INVALID_STATE` guards sit between the version check and the terminal guard — `routes_c.py:191-206`
- §3.7 — insert — ambiguity — release is an arithmetic credit; the `WITHDRAWN` write lands only after every guard passes; an already-terminal supersede credits nothing — `routes_c.py:218-245`
- §3.7 — insert — ambiguity — `countered_price_cents` only strictly positive, no cross-comparison, no buyer recompute — `routes_c.py:291,310-315`
- §3.7 — insert — ambiguity — revise grants no release-first credit; the offer's own deposit is still committed — `routes_c.py:336-343`
- §3.7 — revise — **mismatch** — `ERR_POF_NOT_VERIFIED` is reported **before** `ERR_WHOLESALER_COMPLIANCE_HOLD` (PRD had them reversed; §2.8 already agreed with impl); accept reads no body at all — `routes_c.py:366-368`
- §3.7 — insert — ambiguity — `countered_price_cents` plays no part in the implied fee — `routes_c.py:376-378`
- §3.8 — revise — **mismatch** — agreement execution reports `ERR_OFFER_NOT_ACCEPTED` before the compliance hold — `routes_d.py:56-62`
- §3.8 — insert — ambiguity — execution recomputes the buyer's capital (the `CONSUMED` offer releases its deposit) — `routes_d.py:108-110`
- §3.8 — revise — **mismatch** — `settlement_reference` non-empty ≤200; settlement is not ownership-checked; a `TERMINATED_UPSTREAM` agreement reports `ERR_CONTRACT_TERMINAL`, not `ERR_INVALID_STATE` — `routes_d.py:134-142`
- §3.8 — insert — ambiguity — title-order creation not ownership-checked; `UNDECIDED`/`ASSIGNMENT_ELECTED` both map to an `ASSIGNMENT` order; `buffered_window_end_at` null there — `routes_d.py:159,175-182`
- §3.8 — revise — ambiguity — the capacity test runs only for `DOUBLE_CLOSE`, against the contract's wholesaler's own live windows — `routes_d.py:181-192`
- §3.8 — insert — ambiguity — clear-to-fund and fund-and-close read no body at all — `routes_d.py:229,260`
- §3.8 — insert — ambiguity — reverted double-close election → `ERR_INVALID_STATE`; clearing on an already-`PENDING_CLOSE` contract is a no-op — `routes_d.py:239-256`
- §3.8 — insert — ambiguity — the dual-control comparison precedes both the terminal and state guards; a null `cleared_by_user_id` cannot trip it — `routes_d.py:263-270`
- §3.8 — insert — ambiguity — a deposit already out of `HELD` (or absent) is passed over at funding — `routes_d.py:286-289`
- §3.9 — insert — ambiguity — unlimited disputes per contract; no signature/deposit prerequisite at opening — `routes_d.py:378-403`
- §3.9 — insert — ambiguity — `evidence_ref` non-empty ≤200; the `ADJUDICATED` guard outranks the already-filed guard — `routes_d.py:432,448-451`
- §3.9 — revise — **mismatch** — the deposit test is reported **before** the evidence test (PRD had them reversed); a missing deposit also reports `ERR_DEPOSIT_NOT_HELD`; `rationale` discarded — `routes_d.py:468-485`
- §3.9 — insert — ambiguity — `subject_seller_lead_id` never cross-checked against the wholesaler; opening a review is not hold-gated — `routes_d.py:300-304`
- §3.9 — revise — **mismatch** — segregation checked first of all (even on an already-decided review); mismatched `decision`/`finding` pairing → `ERR_INVALID_STATE`; a `CLEAR` adjudication still re-derives posture and re-runs the hold cascade (PRD said "nothing more") — `routes_d.py:352-374`
- §2.8 rank 21 — revise — **mismatch** — dispute adjudication requires a deposit that exists and is in neither `HELD` nor `APPLIED_AT_CLOSING`; `REFUNDED_TO_WHOLESALER`/`SPLIT_SETTLED` also pass (PRD said it requires `FORFEITED_TO_SELLER`) — `routes_d.py:476`

Pass 3 note: the clock setter needed no change — §2.5 and §3.9 already pin the sole-member `current_utc` response, backwards moves, and the all-buyer recomputation.

### Step 9 aggregate

**58 total edits across the three passes — 39 ambiguity-pins, 19 mismatch-revisions.** All 8 implementation modules audited exactly once.

**Orchestrator independent verification:** `PRD.md` 489 lines / 103040 chars vs `PRD_COMPLETED.md` 489 lines / 121233 chars (**+18193 chars, +17.7 %**); `cmp` confirms the two files are NOT byte-identical (the failure mode where a Step 9 agent no-ops); `diff` reports 100 changed lines (50 per side), consistent with 58 in-paragraph edits concentrated in long paragraph-lines; `grep -c '^#'` returns 29 headings, matching the source's section structure with no sections added or lost; the file still ends with the complete final `| \`ERR_ASSIGNMENT_FEE_CAP_EXCEEDED\` | 422 |` table row, so it is not truncated.

## Pipeline complete — 2026-09-04T17:17:03.964Z

All nine steps done. Final state: 3 scaffold artifacts at the task root; `test_helpers/` (3636 lines, 9 files) and `test_suite/` (5358 lines, 77 tests across 17 modules + conftest) at the task root; `workspace/` holds `INSTRUCTION.md`, `PRD.md`, `PRD_COMPLETED.md`, and `implementation/` (3013 lines, 10 files, 60 endpoints) with all 8 passing `results.{1..8}.json`. Step 8 legitimately skipped (Step 7 needed zero fixes), so there is no `PRD_FINALIZED.md`. Test result: **77/77 in all 8 parallel rounds, zero failures, zero errors, zero skips.**
