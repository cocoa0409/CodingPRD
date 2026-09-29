# Worklog — task_2566_tax_exempt_bond_financed_multifamily_development

## Step 1: Create task directory — 2026-09-03T12:16:00.000Z

Created pre-assigned task directory `/home/ubuntu/github/CodingPRD/tasks/task_2566_tax_exempt_bond_financed_multifamily_development` and its `workspace/` subdirectory. Index 2566 was fixed by the scenario number (no auto-allocation scan, per orchestration instructions, since up to 32 pipelines run concurrently on this host).

## Step 2: Generate scaffold — 2026-09-03T13:47:00.000Z

All three scaffold artifacts for task 2566 are complete and lint-clean.

## Files

| File | Lines |
|---|---|
| `SCAFFOLD.yaml` | 3123 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2675 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 5575 |

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           SCAFFOLD.yaml
  Difficulty design:  SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    61
  §1.1 entities declared:     14
  §1.8 instances scanned:     22
  §1.9 instances scanned:     50
  Calls scanned (§1.8+§1.9):  1239

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## SCAFFOLD.yaml inventory

- `domain_name: tax-exempt-bond-multifamily`, `api_prefix: ""`; profile: `compliance_audit` / `quota_allocation`, layers `optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers`, topology `flat`, shape `parallel`, roles `segregation_of_duties`, consistency `immediate`.
- **14 entities**: Developer, Investor, CapPool, Project, VolumeCapAllocation, BondIssue, DrawRequest, UnitRestriction, RegulatoryAgreement, CostCertification, CreditAllocation, InvestorDelivery, ComplianceReport, PhysicalInspection.
- **13 state machines / 54 transitions** (Project carries two parallel axes: development + compliance), **3 OCC rules** (cap-pool version on award decision, bond-issue version on draw creation, credit-allocation version on delivery creation).
- **11 calculations, 36 ordered validations, 61 endpoints (25 GET / 36 writes incl. the logical clock), 61 error codes, 6 roles.**

## Design indices

- §1.8: 9 rule_ids, **22 instances**.
- §1.9: **62 instances across 9 sections — 50 active + 12 `excluded_because` stubs** (entities 11, state_machines 13/10 active, calculations 10/4, validations 7/6, endpoints 6, errors 4, rbac 4, cross_cutting_complexity_layers 6/4, consistency_model 1).

## Verification performed beyond the linter

- All 61 error codes are asserted by at least one §1.8/§1.9 recipe; all 61 endpoints (including every write) are called in at least one recipe. Closing these two gaps required three additions late in the pass: an active `conditional_action` delivery instance (ERR_NO_UNDELIVERED_CREDIT was cited only by a stub and never triggered anywhere), a cyclic RegulatoryAgreement amendment instance (`POST /regulatory-agreements/{id}/amend` was never exercised), and a seven-family list-filter instance.
- Three SCAFFOLD/design corrections were made: the §1.8 allocation-cycle instance's DENY call was missing its required `expected_cap_pool_version` (lint violation, now uses the already-captured `pool_v1`); `undrawn_amount_cents` → `undrawn_cents`; and SCAFFOLD.yaml's `amend` endpoint side-effect claimed `amendment_count` increments on amend, contradicting the state machine (it counts completed re-recordings) — the endpoint text now matches.
- All three files parse with `yaml.safe_load`, contain no anchors/aliases, no forbidden concurrency vocabulary, and SCAFFOLD.yaml holds neither design key. The scenario block is byte-verbatim. No sibling task directory was read at any point.

Orchestrator verification: all three files parse with yaml.safe_load; SCAFFOLD.yaml top-level keys contain neither design key.

## Step 3: Copy shared files — 2026-09-03T14:07:00.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T14:25:00.000Z

PRD.md is complete at **471 lines**, ending at a real section boundary (last row of the §5 error table).

**Section outline**
- §1 Introduction
- §2 Global Specifications & System-Wide Principles — 2.1 User and Role-Based Access Control / 2.2 API Response Structure (verbatim skill block) / 2.3 Pagination / 2.4 Common Resource Properties, Identity and the Logical Clock / 2.5 Money, Basis Points and Rounding Discipline / 2.6 Optimistic Concurrency on Pool, Issue and Allocation Parents / 2.7 The Order in Which a Request Is Refused / 2.8 Two Independent Status Axes and the Cascade Discipline / 2.9 Conservation Invariants / 2.10 Segregation of Duties and Sponsor Standing
- §3 Business Logic & Workflows — 3.1 Program Onboarding: Sponsors, Investors and the Program-Year Cap Pool / 3.2 Filing a Development and Designating Its Units / 3.3 Volume Cap: Request, Award, Deferral and Recycling / 3.4 Recording and Amending the Land-Use Restriction Agreement / 3.5 Sizing and Closing the Bond Issue / 3.6 Construction Draws and Negative Arbitrage Management / 3.7 Placement in Service, Conversion and Stabilization / 3.8 Cost Certification, Final Allocation and Credit Delivery / 3.9 Ongoing Compliance, Recapture, Inspections and the Passage of Time
- §4 Endpoint Definitions — 61 rows, 4 columns (Method | Path | Description | Authorized Role(s))
- §5 Error Code Catalogue — 61 rows, 2 columns (Error ID | HTTP Status Code)

**Field coverage check:**
- entities[].fields: 165 required, 165 present, 0 missing
- endpoints[].input (request body + query params): 163 required, 163 present, 0 missing
- endpoints[].query_params: covered within endpoints[].input, 0 missing

Status: PASS

**Rule coverage check:**
- validations[] with priority: 36 checked, 36 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_<parent>_version + error_id all named), 0 missing
- state_machines[].transitions: 54 checked (13 machines), 54 fully expressed, 0 missing
- calculations[]: 11 checked, 11 fully expressed, 0 missing
- validations[] conditions: 36 checked, 36 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 36 checked, 36 expressed, 0 missing
- entities[].fields[] structured content: 14 entities checked, 14 reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked (award/deny, approve/reject, accept/return-for-revision, clear/noncompliance, sanction/lift, accept/rescind), 6 with equal prose density, 0 asymmetric

Status: PASS

**Path purity check (§3 only):**
- backtick tokens scanned: 266
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0

Status: PASS

**Coverage vs scaffold declared counts:** entities 14/14, endpoints 61/61, state machines 13/13 (54/54 transitions), calculations 11/11, validations 36/36, errors 61/61, roles 6/6, concurrency rules 3/3.

Notes worth relaying: the scaffold's own transition total is 54 (not 55), and six internal scaffold inconsistencies were resolved in favour of the majority/authoritative source — compliance/extended-use end dates stamped at conversion rather than at recording; `BondTrustee` (not HfaAllocationOfficer) for bond issue/redeem; `HfaAllocationOfficer` (not HfaComplianceOfficer) for cost-cert review; `issued_by_user_id` written at creation and re-stamped at issuance; the inspection buffer conflict set includes MISSED windows; and the amend endpoint's input `extended_use_years` used in place of the precondition-only `new_extended_use_years`. `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced.

Orchestrator truncation guard (per the known doc-generator failure mode): verified PRD.md is 471 lines / 104613 bytes, has all 5 top-level sections with 26 headings, and `tail -25` ends cleanly on the final row of the §5 error table (`ERR_REPORT_COUNTS_INCOHERENT | 422`) — not mid-sentence. No regeneration needed.

## Step 6: Generate implementation — 2026-09-03T15:12:00.000Z

The implementation is complete, verified, and the smoke servers have been killed by PID (ports 18566/18567 confirmed free; no broad `pkill` was used).

## File inventory (`workspace/implementation/`, 3613 lines of Python)

| File | Lines | Responsibility |
|---|---|---|
| `start.sh` | 10 | `cd $(dirname $0)`, guarded `pip install` only when Flask is missing, `exec python3 app.py` |
| `requirements.txt` | 1 | `Flask>=2.0` |
| `app.py` | 63 | App factory, blueprint registration, `ApiError`/404/405/`HTTPException`/catch-all handlers, `0.0.0.0:$PORT` (default 10000) |
| `store.py` | 189 | In-memory `Store` (14 dicts keyed by UUID), logical UTC clock (`2026-08-01T00:00:00.000Z`), ISO-8601 parse/format with 3 fractional digits, `round_half_up` / `floor_div` / `ceil_div`, `new_row`/`touch` (version+1, `updated_at`) |
| `errors.py` | 97 | All 62 PRD §5 error ids -> HTTP status, `ApiError`, `fail()` |
| `envelope.py` | 93 | `meta`/`response_type`/`data` envelopes, pagination (limit 1-100 default 10, offset >= 0) |
| `validation.py` | 123 | Priority-40 body validation; unknown keys ignored; every failure `ERR_INVALID_REQUEST` |
| `auth.py` | 179 | Roles, `ENDPOINT_ROLES` for all 61 keys, `ACTOR_RECORDING` set, ladder rules 1-3 (`guard`, `own_project`/`own_investor`/`own_delivery`) |
| `calc.py` | 381 | The 11 pinned calculations + derived ledgers, all integer cents/bps |
| `serialize.py` | 299 | 14 serializers; every aggregate re-derived at read (no stored ledgers) |
| `domain.py` | 320 | Cross-entity cascades: pool re-derivation, deferral/reinstatement, unit activation/release, stabilization, negative-arbitrage recompute, noncompliance/cure chains, the clock pass |
| `routes/` (10 modules) | 1659 | `reads` (25 GETs), `onboarding`, `units`, `volumecap`, `agreements`, `bonds`, `draws`, `certs_credit`, `compliance`, `clock` |

## Organization

- **61 endpoints** — programmatically verified: the Flask URL map matches the PRD §4 table exactly (61 registered, 61 declared in `ENDPOINT_ROLES`, zero extra, zero missing).
- **13 state machines** — each transition endpoint checks its own `*_STATE_INVALID` at priority 81; the sponsor machine reports `ERR_DEVELOPER_NOT_ACTIVE` instead. Time-driven transitions (award expiry, inspection no-show, RESTRICTED->EXTENDED_USE->RELEASED) live only in `domain.advance_clock`.
- **11 calculations** in `calc.py`, rounding per PRD §2.3: round-half-up for issuance allowance, per-period arbitrage accrual, annual credit, recapture exposure; floor for all bps ratios and each intermediate rent/qualified-basis division; ceil for the 500,000-cent denomination step. The arbitrage series stores each rounded per-period accrual on its draw *before* summing, walking `period_start`/`draw_number` order with the undrawn balance **before** each draw.
- **36 ordered validations** — handlers follow the priority bands: auth (10/20) -> best-effort ownership (30) -> body (40) -> path 404 (50) -> FK 404 in declaration order (60) -> OCC (70) -> developer-active (80) -> state (81) -> 82/85-90 -> temporal (100-103) -> fiscal (110-116) -> safety (120-121) -> constraint (130-136). Ownership is attempted pre-validation via `soft_get` and re-checked after resolution so a 404 never leaks as a 403.
- **3 OCC guards** at priority 70, before any state check: `expected_cap_pool_version`, `expected_bond_issue_version`, `expected_credit_allocation_version`.
- **Storage**: process memory only, no file/SQLite/JSON/tmp, nothing seeded — a fresh boot returns `total_count: 0` on all 11 list endpoints (verified).

## Smoke-test result

Two scripted end-to-end sweeps against a live server on ports 18566/18567: **0 failures out of ~70 assertions.** Covered the full happy arc (sponsor -> pool -> development -> units -> cap award -> agreement recording -> bond sizing/closing -> draw approve/fund -> operating months -> conversion -> cost certification -> credit allocation/issue -> delivery/accept -> compliance report -> recapture cascade -> cure -> inspection -> clock rollovers) plus the refusal ladder (401/403 ownership/403 segregation/400/404/412 stale version/409 overlap, duplicate, state, buffer conflict/422 AMI, term, counts, outside-period). Arithmetic spot-checks all matched hand computation: par 51,102,000,000 with a 1,002,000,000 allowance; arbitrage accrual 85,170,000 on the pre-draw undrawn balance; qualified basis 588,000,000 -> annual 19,404,000 -> total 194,040,000; price 2,576 bps; recapture 3,880,800; restricted rent 112,500 (and the 25,000-cent floor raising a 22,500 result); denomination round-up 510,000 -> 1,000,000.

Two judgement calls worth flagging: `POST /_clock/set_current_utc` returns `data: {}` (SCAFFOLD declares `output: null`), and unit list ordering is plain lexicographic on the string `unit_number` (I replaced an earlier natural-sort with the literal "ordered by `unit_number` ASC" reading).

## Step 5: Generate unit tests — 2026-09-03T17:00:00.000Z

Orchestrator note: the first Step 5 subagent died mid-run from a transient API error ("Agent terminated early due to an API error") after finishing `test_helpers/` but before creating `test_suite/` at all. Per the resume protocol, the SAME agent was resumed via SendMessage with a computed to-do list (the 72 active `Design:` tags, written to `/tmp/task2566_todo.txt` by an orchestrator script that filtered out the 12 `excluded_because` stubs) rather than respawning a fresh generator — a fresh agent would have re-derived `test_helpers/` and made the suite diverge from itself. Its completion report follows verbatim.

Generation is complete. Both directories are final, everything compiles, and pytest collects 71 tests cleanly.

## File inventory

`test_helpers/` (3,987 lines): `__init__.py` 410, `api_client.py` 685, `api_errors.py` 166, `assertions.py` 614, `constants.py` 273, `factories.py` 423, `fixtures.py` 940, `test_users.py` 128, `types.py` 348.

`test_suite/` (6,251 lines): `conftest.py` 31 (no tests) plus

| file | lines | tests |
|---|---|---|
| test_01_sponsor_registry_and_developments.py | 519 | 11 |
| test_02_unit_designation_and_fractions.py | 645 | 9 |
| test_03_volume_cap_pool.py | 977 | 9 |
| test_04_regulatory_agreement.py | 500 | 5 |
| test_05_bond_sizing_and_issuance.py | 630 | 7 |
| test_06_draw_requests_and_arbitrage.py | 429 | 6 |
| test_07_operating_history_conversion_and_cost_certification.py | 487 | 6 |
| test_08_credit_allocation_and_delivery.py | 876 | 8 |
| test_09_compliance_and_inspections.py | 640 | 5 |
| test_10_access_control_and_listing.py | 517 | 5 |

**Total: 71 tests.**

## Instance coverage

72 active instances (22 queue A + 50 queue B) -> **71 translated, 1 skipped**. Queue A: 22/22 translated. Queue B: 49/50 translated.

Skip (one line, per the PRD-first filter):
- `Corner/state_machines/the_agreement_amendment_loop_repeats_and_counts_only_the_recordings_that_complete_it` — the instance asserts a re-recording re-derives `compliance_period_end_date`, but PRD §3.4 re-derives only `extended_use_end_date` on re-recording, so the asserted outcome is not uniquely derivable.

## Tag audit (scripted, AST-based)

- 71 test functions, 71 `Design:` lines — exactly one per test, and it is the last non-blank line of every docstring.
- All 71 tags are distinct and every one appears verbatim in `/tmp/task2566_todo.txt`; no tag outside the to-do list.
- Every test also carries at least one `PRD: "..."` verbatim citation.
- `python3 -m compileall` clean over both directories; `pytest --collect-only` -> 71 collected, 0 errors.
- A static cross-check confirmed every `fixtures.*`, `factories.*`, `constants.*` and `api.*` symbol referenced by the suite exists, every name imported from `test_helpers` is exported, and no test file has an unused import.

## Helper bugs fixed while writing tests (2)

Both were the same duplicate-keyword class (a value passed explicitly *and* forwarded through `**overrides`, raising `TypeError` for any caller that overrode it): `fixtures.record_month` and `fixtures.file_compliance_report`, each fixed with the merged-`spec` pattern.

## Design corrections to report (4 instances translated with a deviation)

1. `Difficulty/cross_entity_state_dependency/cost_certification_submission_depends_on_the_sponsor_being_reinstated` and `Difficulty/non_linear_state_machine/cost_certification_returns_to_submitted_twice_and_locks_after_acceptance` — both design setups contradict PRD §3.8 ¶299 (certification drafting requires the in-service ladder). Translated on the canonical ladder; the incidental values were re-derived from the PRD (final fifty-percent ratio 5000, `automatic_credit_triggered` true), where the design asserted unreachable 0/false.
2. `Corner/rbac/form_8609_issuance_is_refused_for_the_awarding_officer_and_for_the_reviewing_officer_but_clears_for_a_third` — design asserts `issued_by_user_id == null` after the refusals, contradicting PRD §2.10 and §3.8 (the field is stamped at *creation*, by hfa-alloc-3). Kept the instance's core claim (both prior identities 403, third clears, PENDING with null `form_8609_number`) and dropped the contradictory null assertion.
3. `Difficulty/transitive_cascade/noncompliance_finding_cascades_project_then_credit_allocation_then_accepted_delivery` — design assumes a `compliance_start_date` on a merely `PLACED_IN_SERVICE` development, but PRD §3.7 stamps it only at conversion. Test converts the bond first (span 2027-03-01...2057-03-01) and asserts `development_status` stays `STABILIZED` where the design said `PLACED_IN_SERVICE`.

No broad `pkill` was run, and no server was started by this work.

## Step 7: Run tests and iterate — 2026-09-03T16:40:00.000Z

# Summary

**Iterations run:** 2 full 8-round parallel sweeps (baseline: 68/71 in all 8 rounds, 3 identical failures, zero flakiness; final: 71/71 in all 8 rounds).

## Tests deleted (PRD-silence / non-unique-derivability)

- `test_suite/test_03_volume_cap_pool.py` :: `test_sponsor_project_count_and_pool_aggregates_reconcile_after_a_withdrawal` — removed ONLY the assertion `sponsor_3["version"] > sponsor_2["version"]` ("the sponsor row was itself mutated by the cascade, so its version moves"). **Pattern: BRANCH-ASYMMETRIC SIDE EFFECT / partial coverage (STEP 1c).** PRD §3.5's redemption paragraph exhaustively enumerates the version effects — "Both the development's `version` and the pool's `version` increment by 1." — and does not name the sponsor, while PRD names sponsor version bumps explicitly everywhere it wants them (§3.2 filing: "increments the sponsor's `version` by 1"; §3.1 sanctions: "Each sanction action increments the sponsor's `version` by 1"). Since `active_project_count` is "derived, not supplied", a faithful implementer that derives it never mutates the sponsor row, so §2.8's "every affected row" does not reach it. Both implementations are articulable. All other assertions in the test were kept, including `active_project_count == 2` (the test's actual subject) and the pool-ledger and sibling checks.

## Fixes to `test_suite/` (test-vs-PRD consistency, STEP 2)

- `test_suite/test_04_regulatory_agreement.py` :: `test_a_clock_past_the_extended_use_end_releases_the_agreement_and_its_units` — the precondition check asserted the derived dates as exact strings `"2042-03-01T00:00:00Z"` / `"2057-03-01T00:00:00Z"`, over-specifying the *rendering* on top of the PRD rule (§3.7 date arithmetic) and contradicting PRD §2.4 "Timestamps are ISO 8601 in UTC with exactly three fractional digits". The server returned arithmetically-correct `2042-03-01T00:00:00.000Z` / `2057-03-01T00:00:00.000Z`. Rewrote it to the suite's own convention: `status="RECORDED"` via `assert_fields` plus a `startswith` loop over the two instants — byte-for-byte the same construct `test_07_operating_history_conversion_and_cost_certification.py:173-181` uses on the *same two fields of the same agreement with the same expected instants*, and the same convention as `test_09:62-63`, `test_04:213`, `test_07:53`, `test_08:389`. The date values asserted are unchanged; only the fraction-digit over-specification was dropped. (Corroborating: `test_helpers/assertions.py::parse_instant` uses `strptime(value.replace("Z",""), "%Y-%m-%dT%H:%M:%S")`, which cannot parse a fraction at all — the exact-string form was the lone outlier in the suite.)

No changes were needed in `test_helpers/`.

## Fixes to `implementation/` (STEP 3)

Root cause: `total_credit_accepted_cents` was derived at read time from deliveries currently in `ACCEPTED`, so the §3.9 recapture cascade (`ACCEPTED` -> `RECAPTURE_FLAGGED`) silently zeroed the investor ledger. PRD makes the counter stored-and-delta'd: §3.1 "it is re-derived whenever a delivery is accepted or an accepted delivery is rescinded" (exactly two triggers, flagging not among them), §3.8 "raises the investor's `total_credit_accepted_cents` by the delivered amount", §3.8 rescind "The one asymmetry ... rescinding a delivery that had reached `ACCEPTED` also lowers that investor's `total_credit_accepted_cents` by the delivered amount, whereas rescinding one still in `DELIVERED` leaves the investor ledger alone", and §3.9 "a flagged delivery keeps counting toward the allocation's `delivered_credit_cents` while flagged."

- `workspace/implementation/routes/onboarding.py` — `create_investor()`: initialize the stored field to `0` ("An investor opens with `total_credit_accepted_cents` at zero").
- `workspace/implementation/serialize.py` — `investor()`: read the stored field instead of calling `calc.investor_accepted_total(row)`.
- `workspace/implementation/routes/certs_credit.py` — `accept_delivery()`: raise the stored counter by `delivered_credit_cents` before `touch(investor)`.
- `workspace/implementation/routes/certs_credit.py` — `rescind_delivery()`: lower the stored counter by `delivered_credit_cents`, inside the pre-existing `if previous == "ACCEPTED"` branch only, preserving the PRD's stated asymmetry.

No endpoint, response field, side effect or header was added; storage remains in-memory dicts; nothing is seeded at startup.

## Final sweep (all 8 rounds)

| round | passed/total | duration |
|---|---|---|
| 1 | 71/71 | 129.4s |
| 2 | 71/71 | 129.4s |
| 3 | 71/71 | 129.4s |
| 4 | 71/71 | 129.2s |
| 5 | 71/71 | 129.5s |
| 6 | 71/71 | 129.5s |
| 7 | 71/71 | 129.4s |
| 8 | 71/71 | 129.4s |

Zero failures, zero errors, zero skips in every round — the union of failing tests across all 8 rounds is empty. All eight `results.*.json` confirmed present and non-empty on disk (~25 KB each, all valid JSON).

One process-note worth carrying forward: `sweep.log` is unusable for outcomes under 8 concurrent rounds — its lines interleave and corrupt (it showed 45 `FAILED` tokens against a true 24, and mis-attributed failures to three tests that in fact passed in all 8 rounds). Only the per-round `results.${i}.json` `tests[].status` fields are authoritative; the schema is `{total, passed, failed, errors, skipped, duration_seconds, tests:[{name, file, status, duration_seconds, error_message}]}` (`status`/`name`, not `outcome`/`nodeid`).

Orchestrator verification (independent of the subagent's claim, per the Step 7 sweep-artifact check): all 8 `results.*.json` exist on disk and each parses to `passed == total == 71`.

## Step 8: Finalize PRD — 2026-09-03T16:53:00.000Z

Done. `PRD_FINALIZED.md` written with two in-place sentence revisions, both in §3.1.

**Line counts:** PRD.md 471 -> PRD_FINALIZED.md 471 (0.0% delta). Final line is still the §5 error-table row `| ERR_REPORT_COUNTS_INCOHERENT | 422 |`.

**Changes**
- §3.1 (investor registration) — revise — `total_credit_accepted_cents` re-stated as a **stored running total** moved by exactly two events (accept `+delivered_credit_cents`; rescind-from-`ACCEPTED` `-delivered_credit_cents`), explicitly unaffected by `ACCEPTED`->`RECAPTURE_FLAGGED` and the cure's `RECAPTURE_FLAGGED`->`ACCEPTED`. Replaces the old "sum over deliveries whose status is `ACCEPTED` ... re-derived" phrasing, which the §3.9 recapture cascade would zero out. — `implementation/routes/onboarding.py:84`, `implementation/serialize.py:38`, `implementation/routes/certs_credit.py:309-312`, `:341-347`
- §3.1 (sponsor registration) — insert — `active_project_count` is derived **at read time**, so a development's `development_status` change (including the redemption move to `WITHDRAWN`) alters what the counter reports **without mutating the sponsor row**; the sponsor's `updated_at`/`version` move only on a sanction action or a new development filing. — `implementation/serialize.py:27`, `implementation/calc.py:375-377`, `implementation/routes/onboarding.py:68`, `:152`

**Step 7 item that needed no PRD edit:** the `test_04_regulatory_agreement.py` date-string fix. PRD §2.4 ("exactly three fractional digits") already determines the `.000Z` rendering the server produced; the exact-string assertion was the test's own over-specification, so PRD prose stays verbatim. (I deliberately did not add a universal "all date fields carry three fractional digits" claim — client-supplied dates such as `placed_in_service_date` are echoed raw at `certs_credit.py:157/181`, so such wording would have been a new mismatch.)

**Pre-edit search log**

Edit 1 — investor accepted ledger
- (a) Subject: `total_credit_accepted_cents` — every write, read and would-be re-derivation.
- (b) Enumerated: `grep -rn "total_credit_accepted_cents\|investor_accepted_total"` over all of `implementation/` -> only 4 write/read sites (`onboarding.py:84` init 0; `serialize.py:38` reads stored; `certs_credit.py:309` accept `+`; `certs_credit.py:344` rescind `-`, inside `if previous == "ACCEPTED"`). Read `certs_credit.py` in full (accept/rescind/create-delivery paths); read `domain.py:211-258` (`noncompliance_cascade`, `cure_cascade`) and grepped `RECAPTURE_FLAGGED` (`calc.py:332`, `domain.py:239`, `:256`) to confirm flagging/unflagging never touch the investor row; confirmed `calc.investor_accepted_total` is now dead and nothing else recomputes the field; confirmed rescind is unreachable from `RECAPTURE_FLAGGED` (`certs_credit.py:329`).
- (c) Adjustment: added the explicit "no other transition adjusts it" clause naming both the flag and the cure directions, rather than only the §3.9 flagging direction — the cure path (`domain.py:255-258`) also leaves the counter alone, and a flag-only sentence would have left the cure open to a double-count reading. Kept §3.8's existing accept/rescind sentences verbatim since they already match the delta semantics.

Edit 2 — sponsor row mutation / `active_project_count`
- (a) Subject: when the `Developer` row is mutated (version/updated_at) and how `active_project_count` is produced.
- (b) Enumerated: `grep -rn "db.developers"` (only `onboarding.py:24` create, `:41` sanction fetch, `:122` filing fetch, `reads.py:22/24` GET, `domain.py:49` lookup) and `grep touch` on developer (`onboarding.py:68` sanction, `:152` filing) — no other route touches it; `serialize.py:27` -> `calc.developer_active_project_count` (`calc.py:375`) recomputes from live projects; read `store.py:176` `touch`; checked every `development_status` writer (bond close, first funded draw, first operating month, conversion, redemption/`WITHDRAWN`) — none touch the sponsor.
- (c) Adjustment: scoped the claim to "a later change to one of the sponsor's developments ... without itself mutating the sponsor row" and enumerated the two real bump triggers (sanction, filing) instead of writing a bare "cascades never touch the sponsor" — filing *does* bump the sponsor's version (`onboarding.py:152`, matching §3.2), so the unscoped wording would have contradicted §3.2 and the impl.

Orchestrator verification: PRD_FINALIZED.md is 471 lines (same as PRD.md), 105351 bytes vs 104613, and its last line is the §5 error-table row `| ERR_REPORT_COUNTS_INCOHERENT | 422 |` — not truncated.

## Step 9: Complete PRD — 2026-09-03T17:45:00.000Z

Orchestrator decision (written here per the autonomy instruction): Step 9 was run as **three sequential file-partitioned passes** over `implementation/` rather than one subagent, because a single-pass scan of a 3,600-line implementation against a 471-line/105 KB PRD reliably no-ops (the tell being a PRD_COMPLETED.md byte-identical to its source). Each pass owned a disjoint slice of `implementation/`, edited the SAME PRD_COMPLETED.md in place, and was handed the prior passes' explicit "left to a later pass" notes so cross-file findings were not dropped. Pass A created the file from PRD_FINALIZED.md; B and C amended in place and each verified the earlier passes' edits had survived.

Partition: **Pass A** = store.py, envelope.py, validation.py, auth.py, errors.py, app.py, routes/onboarding.py, routes/units.py. **Pass B** = routes/volumecap.py, routes/agreements.py, routes/bonds.py, routes/draws.py, routes/clock.py. **Pass C** = routes/certs_credit.py, routes/compliance.py, routes/reads.py, serialize.py, calc.py, domain.py.

### Totals

Source `PRD_FINALIZED.md` 471 lines / 105,351 chars -> `PRD_COMPLETED.md` 471 lines / **126,884 chars (+21,533)**. 216 diff lines. No new sections and no new paragraphs — the heading list is byte-identical to PRD.md's 27 headings; every edit is an in-paragraph insert or revision. **60 edits total: 45 ambiguity-pins, 15 mismatch-revisions.**

| pass | ambiguity-pins | mismatch-revisions | chars added |
|---|---|---|---|
| A | 12 | 4 | +5,219 |
| B | 14 | 8 | +7,265 |
| C | 19 | 3 | +9,049 |

### Pass A changes (16)

- §2.1 — revise — ambiguity — an `X-User-Role` outside the six exact spellings (unknown or mis-cased) is `ERR_FORBIDDEN_ROLE`, not 401/400 — `auth.py:145-147`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` plus exactly 20 uppercase-alphanumeric characters — `store.py:114-118`
- §2.2 — insert — ambiguity — `api_request_timestamp` comes from host real time, not the logical clock — `envelope.py:15-19`, `store.py:59-60`
- §2.3 — revise — ambiguity — blank / non-integer `limit` or `offset` is also `ERR_INVALID_REQUEST`, parsed after the role check — `envelope.py:54-81`
- §2.4 — insert — ambiguity — `created_at`/`updated_at` are the two fields stamped from host real time; every other transition-written instant comes from the logical clock — `store.py:163,178`
- §2.4 — revise — **mismatch** — "Nothing in this service reads the host's wall clock" narrowed to "no business rule...", since bookkeeping stamps and `api_request_timestamp` do — `store.py:59,163,178`
- §2.7 rule 1 — insert — ambiguity — the acting-user endpoints requiring `X-User-ID` are exactly the five that write an operator id (cap decision, cost-cert review, credit-allocation create, credit-allocation issue, compliance-report review); trustee transitions, sanctions and the clock need only the role header; the requirement keys off the supplied role, not the endpoint's allow-list — `auth.py:103-109,142-143`
- §2.7 rule 3 — insert — ambiguity — registry reads compare the fetched row itself (`GET /developers/{id}`, `GET /investors/{id}`); a nonexistent row skips the ownership test and yields the 404; no list endpoint is ownership-scoped — `auth.py:151-179`
- §2.7 rule 4 — revise — ambiguity — datetimes need full date+time terminated by `Z`; a bare calendar date or a numeric offset is malformed; fractional seconds optional 1-9 digits; lowercase `t`/`z` tolerated; explicit `null` in an optional field = absent -> default — `store.py:22-24`, `validation.py:25-27,100-115`
- §2.7 rule 4 — insert — ambiguity — a JSON boolean or numeric string is never an integer — `validation.py:53-56`
- §3.1 — revise — **mismatch** — sponsor `tax_id` uniqueness is unenforced (no §5 error exists); all three fields must be non-blank — `routes/onboarding.py:17-31`
- §3.1 — revise — **mismatch** — investor `tax_id` uniqueness likewise unenforced — `routes/onboarding.py:72-86`
- §3.1 — revise — **mismatch** — pool `program_year` uniqueness unenforced; `program_year` is an integer >= 1 — `routes/onboarding.py:89-101`
- §3.2 — insert — ambiguity — the `developer_id` ownership comparison outranks payload checks and `ERR_DEVELOPER_NOT_FOUND` whenever the supplied value is a string — `routes/onboarding.py:109-124`
- §3.2 — insert — ambiguity — designation is gated on neither status axis nor sponsor standing; a unit added after stabilization opens `PROPOSED` and is never retroactively activated, yet counts toward the fractions at once — `routes/units.py:37-79`, `domain.py:129-136`
- §3.2 — insert — ambiguity — PATCH requires `designation` even when unchanged; `bedroom_count`/`floor_space_sqft` cannot be restated; omitted optionals keep stored values; an omitted band carries forward on a `RESTRICTED` patch and is cleared without error on a patch to `MARKET`/`EMPLOYEE_UNIT`; the `RELEASED` state check precedes the AMI rules — `routes/units.py:82-118`
- §5 — insert — ambiguity — off-contract responses: unrouted path -> `ERR_NOT_FOUND` 404; undeclared method on a documented path -> `ERR_INVALID_REQUEST` at **HTTP 405**; trailing slashes tolerated — `errors.py:77`, `app.py:20,31-38`

### Pass B changes (22)

- §2.7 rule 8 — revise — mismatch — sponsor-standing endpoint set was declared "precise" but omitted the award branch of the decision endpoint, where the check also sits *after* the state rule — `routes/volumecap.py:79-86`
- §3.3 ¶1 — insert — ambiguity — `requested_closing_date` unconstrained and never re-read; `pool_status` is not a gate on requesting; both-FK-bad reports `ERR_CAP_POOL_NOT_FOUND` first — `volumecap.py:26-30`
- §3.3 ¶1 — revise — mismatch — the one-live-allocation invariant is tested only at create; revise can yield a second live allocation — `volumecap.py:34`, `143-170`
- §3.3 ¶2 — insert — ambiguity — `expiry_date` accepted as supplied, may already be lapsed — `volumecap.py:66`
- §3.4 ¶1 — insert — ambiguity — multiple agreements per development allowed; "the recorded agreement" = earliest-created RECORDED — `agreements.py:31-65`, `domain.py:147-151`
- §3.4 ¶2 — insert — ambiguity — zero/negative year terms give `ERR_EXTENDED_USE_TOO_SHORT`, not `ERR_INVALID_REQUEST` — `agreements.py:20-28`, `39-40`
- §3.4 ¶4 — insert — ambiguity — compliance-axis move happens only from `UNRESTRICTED`; otherwise no project touch — `agreements.py:104-107`
- §3.4 ¶5 — **revise — MISMATCH (delegated)** — amendment may only restate the development's own election (`ERR_SET_ASIDE_MISMATCH` otherwise), never rewrites it, and `set_aside_ratio_bps`/`set_aside_satisfied` are always derived from the *development's* election, so an amendment cannot change them; also documented the previously-undeclared optional `set_aside_election` input — `agreements.py:119-145`, `serialize.py:69-71`, `calc.py:149-150`
- §3.4 ¶6 — revise — mismatch — re-recording re-derives **both** end dates, on the agreement and the development's mirrors — `agreements.py:99-101`, `domain.py:183-193`
- §3.5 ¶1 — insert — ambiguity — the named award need not belong to the named development; multiple `DRAFT` issues allowed but only the first can close — `bonds.py:42-46`
- §3.5 ¶4 — insert — ambiguity — `closing_date` tested only against award expiry, not the clock — `bonds.py:25-26`
- §3.5 ¶6 — insert — ambiguity — a closing on a non-`PLANNING` development leaves the axis but still rewrites both fifty-percent fields and bumps `version` — `bonds.py:118-122`
- §3.6 ¶1 — revise — mismatch — `draw_number` uniqueness is claimed but unenforced; no error reports a repeat — `draws.py:33`
- §3.6 ¶3 — insert — ambiguity — draw state precedes issue state on decide/fund/void — `draws.py:102-105`
- §3.6 ¶4 — insert — ambiguity — `funding_date` enters no calculation and is unvalidated — `draws.py:128`
- §3.6 ¶5 — revise — mismatch — the series re-run re-stamps only draws whose accrual actually changed — `domain.py:198-206`, reached from `draws.py:159,191`
- §3.7 ¶1 — insert — ambiguity — `occupied_units` uncapped (occupancy may exceed 10,000 bps); zero NOI/debt service allowed — `bonds.py:139-141`
- §3.7 ¶2 — insert — ambiguity — the placed-in-service milestone fires only from `UNDER_CONSTRUCTION` and is spent on the first month — `bonds.py:166-170`
- §3.7 ¶3 — insert — ambiguity — `conversion_date` compared against nothing though it becomes `compliance_start_date` — `bonds.py:180`
- §3.7 ¶6 — revise — mismatch — the stabilization cascade fires only from `PLACED_IN_SERVICE`; unit activation happens even when no `RECORDED` agreement is found, leaving all four end-date fields null — `bonds.py:208-209`, `domain.py:164-180`
- §3.9 ¶last — insert — ambiguity — the clock may be set backwards or repeated; same pass runs, nothing reverses, no monotonicity error — `clock.py:17-18`, `domain.py:272-309`
- §4 clock table row — **insert — ambiguity (delegated)** — response carries an empty `data` object; the new `current_utc` is not echoed — `clock.py:19`, `envelope.py:31-32`

### Pass C changes (22)

- §2.3 — revise — ambiguity — `unit_number` ASC is plain lexicographic string order (`"10"` before `"2"`); reports/inspections carry `created_at` as secondary key; every list ordering is made total by an internal, non-exposed row-creation sequence — `reads.py:167-168, 208, 247, 257` / `calc.py:45`
- §2.3 — insert — ambiguity — filter matching is decimal-string comparison, null field never matches, and an unknown/unparseable/blank filter value is not an error but matches nothing (200, `total_count` 0); undocumented query params ignored — `reads.py:146-153`
- §2.7 rule 12 — revise — **mismatch** — `ERR_PROJECT_NOT_PLACED_IN_SERVICE` also guards `POST /cost-certifications/{id}/submit`, ranked after that endpoint's own state rule — `certs_credit.py:85-91`
- §2.9 — insert — ambiguity — all three ledgers (plus `active_project_count`, the designation counters, three fractions, set-aside ratio/satisfied, `imputed_household_size`) are derived at read time; everything else is read back as stamped — `serialize.py:27, 50, 68-71, 118, 161, 217`
- §3.2 — insert — ambiguity — `imputed_household_size` is reported on every unit, `MARKET`/`EMPLOYEE_UNIT` included — `serialize.py:161`
- §3.2 — insert — ambiguity — AMI schedule is not extrapolated past six; imputed size >=7 clamps to the six-person row (10,440,000) — `calc.py:202`
- §3.7 — insert — ambiguity — zero annualized debt service yields `dscr_bps` 0, so such a window always fails `ERR_DSCR_BELOW_MINIMUM` — `calc.py:272`
- §3.7 — insert — ambiguity — end-date stamping is calendar-year addition preserving month/day/time, with 29 Feb -> 28 Feb in non-leap target years, and is emitted in canonical 3-fractional-digit form (unlike the verbatim `compliance_start_date`); same rule for §3.4's re-derivation — `store.py:63-72` via `domain.py:173-176, 188-189`
- §3.8 — insert — ambiguity — drafting's eligible <= depreciable check is an ordinary payload check, ahead of the project 404 — `certs_credit.py:34-39`
- §3.8 — insert — ambiguity — submit re-tests the ceiling with restated values standing in for stored ones (`ERR_INVALID_REQUEST`, after the 404, before standing/state); `reviewed_by_user_id` is not cleared on resubmission — `certs_credit.py:73-99`
- §3.8 — insert — ambiguity — the accept branch also writes `deficiency_notes` from the payload (clearing it when omitted) — `certs_credit.py:126`
- §3.8 — revise — **mismatch** — the final fifty-percent numerator sums FUNDED draws across **every** issue the development holds, in any issue state — `certs_credit.py:132-136`
- §3.8 — insert — ambiguity — segregation blocks the cost-cert reviewer plus the `decided_by_user_id` of the *earliest-created* cap allocation in `AWARDED`/`COMMITTED`/`RELEASED`/`EXPIRED` only (deniers, deferrals and returned awards do not block) — `certs_credit.py:213-223`
- §3.8 — insert — ambiguity — only `ISSUED` and `RECAPTURE_PENDING` admit a delivery create; `PENDING`/`RECAPTURED` give `ERR_CREDIT_ALLOCATION_STATE_INVALID` after the version guard — `certs_credit.py:264-266`
- §3.9 — revise — **mismatch** — a negative `average_ami_percent` is `ERR_INVALID_REQUEST` at the payload band; 0 and >80 are `ERR_REPORT_COUNTS_INCOHERENT` — `compliance.py:33, 60-63`
- §3.9 — insert — ambiguity — a not-yet-stabilized development has no span, so any `reporting_year` gets `ERR_DUPLICATE_COMPLIANCE_REPORT` — `compliance.py:43-47`
- §3.9 — insert — ambiguity — the review branches land in the terminal statuses `CLEARED` / `NONCOMPLIANCE_FOUND` (the former was never named) — `compliance.py:108, 118`
- §3.9 — revise — ambiguity — the cure threshold is the *highest* `reporting_year` among all `NONCOMPLIANCE_FOUND` reports, not the year of the finding that moved the axis — `domain.py:261-267`, `compliance.py:113-115`
- §3.9 — insert — ambiguity — the second-finding branch stops after `RECAPTURED`: exposure not re-stamped, axis left `NONCOMPLIANT`, deliveries not revisited — `domain.py:215-224`
- §3.9 — insert — ambiguity — no compliance period => `ERR_INSPECTION_OUTSIDE_COMPLIANCE_PERIOD`, but only after the (vacuously passed) buffer test — `compliance.py:155-159`
- §3.9 — insert — ambiguity — an out-of-window `completed_date` is `ERR_INVALID_REQUEST`, tested after the state rule — `compliance.py:191-196`
- §3.9 — insert — ambiguity — one clock pass chains `RESTRICTED` -> `EXTENDED_USE` -> `RELEASED`, firing the release cascade and bumping `version` twice — `domain.py:298-309`

### Coverage statement

Pass C reports that after its pass every behavior in its six files traces to a PRD sentence, with two deliberately untraced classes, both correct: unreachable dead guards (`floor_div`/`ceil_div`/`round_half_up` zero-denominator branches, `fifty_percent_ratio`'s and `applicable_fraction`'s zero-denominator paths, `price_per_credit_dollar_bps`'s zero-delivered path — all unreachable because the relevant fields carry validated minimums of at least 1) and `calc.investor_accepted_total`, which Step 7 left as dead code when it moved the investor ledger to stored-and-delta'd.

### Orchestrator verification

- `PRD_COMPLETED.md` is **not** byte-identical to `PRD_FINALIZED.md` (216 diff lines, +21,533 chars) — the scan genuinely ran, which is the specific failure mode the three-pass split defends against.
- 471 lines, ends on the §5 error-table row `| ERR_REPORT_COUNTS_INCOHERENT | 422 |` — not truncated.
- `diff` of the heading lists of PRD.md and PRD_COMPLETED.md is empty: 27 identical headings, so no section was added or renamed across all three passes.
- `implementation/` was not modified by Step 9 (PRD-only edits), so the Step 7 green sweep still stands: all 8 `results.*.json` remain on disk at 71/71.

**Pipeline complete.** Step 9 has written `workspace/PRD_COMPLETED.md`.
