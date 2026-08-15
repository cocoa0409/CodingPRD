# Worklog — task_1548_treasury_management_lockbox_services

## Step 1: Create Task Directory — 2026-08-13T20:23:00.000Z

Task directory `tasks/task_1548_treasury_management_lockbox_services/` and `workspace/` pre-created and pre-assigned by the pipeline launcher; treated as DONE per instructions.

## Step 2: Generate Scaffold — 2026-08-13T20:53:51.000Z

All three files written and lint-clean. Summary:

## Summary

**Files written:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1548_treasury_management_lockbox_services/SCAFFOLD.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_1548_treasury_management_lockbox_services/SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_1548_treasury_management_lockbox_services/SCAFFOLD_CORNER_DESIGN.yaml`

**Lint verdict:** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`

**Counts:**
- Entities: 14 (Bank, Customer, ServiceAgreement, LockboxSite, TransmissionFormat, RemittanceBatch, RemittanceItem, AvailabilitySchedule, ExceptionItem, ImageRetrievalRequest, AnalysisCycle, AnalysisLineItem, SLAIncident, ErrorCreditRequest)
- State machines: 12 (Bank, Customer, ServiceAgreement, LockboxSite, TransmissionFormat, RemittanceBatch with 3 parallel dimensions, RemittanceItem, ExceptionItem, ImageRetrievalRequest, AnalysisCycle, SLAIncident, ErrorCreditRequest)
- Calculations: 10 (availability_assignment, same_day_credit, earnings_credit, gross_service_charges, net_amount_due, average_collected_balance, sla_error_rate, business_date_rollover, exception_auto_decision_date, image_retention_expiry)
- Endpoints: 119 (includes 13 canonical flat single-GETs + 13 flat filtered-list GETs for FK reverse-reachability, plus nested workflow endpoints, plus `/_clock/set_current_utc` test-driving endpoint)
- Errors: 26
- Roles: 8 (BankOperationsAdmin, TreasuryImplementer, TreasuryActivator, LockboxOperator, CustomerOperator (entity_backed:Customer), BillingSpecialist, BillingApprover, Auditor)
- Concurrency rules (OCC): 3 (agreement-activate, transmission-format-activate, analysis-cycle-settle)
- §1.8 difficulty instances: 18 (exactly 2 per rule × 9 rules)
- §1.9 corner instances: 25 active + 6 excluded-as-covered stubs = 31 total

**Notable design decisions (max-difficulty choices):**

1. **Compound state machine on RemittanceBatch**: three parallel state dimensions (capture_status × transmission_status × derived batch_status) — batch_status is a pure function of child states, never directly writable, which forces implementers to keep derived state coherent.

2. **Segregation-of-duties role model**: activator ≠ implementer, closer ≠ capturer, decider ≠ raiser, approver ≠ settler — enforced via X-User-ID comparisons, all mapped to `ERR_SEGREGATION_OF_DUTIES`.

3. **Dual-variant calculations on different domains**: (a) `same_day_credit` (provisional vs final on RemittanceBatch) and (b) `earnings_credit` (with_agreement_override vs with_bank_default on Customer billing) — different entity domains per Rule 1.

4. **Combinatorial formulas in different modes**: (a) `availability_assignment` is a 3-input tiered selector (priority + effective_from + created_at tiebreak), (b) `gross_service_charges` pins per-line-rounding-then-sum order.

5. **Boundary precision**: SLA breach uses `>=` (at threshold IS breach); cutoff uses `>=` (exactly AT cutoff rolls to next business day). Both reachable via different endpoints.

6. **Cascades of depth 3 and 2**: Bank.suspend → Site.SUSPENDED → Batch.HELD (depth 3); item.raise_exception → ExceptionItem created → Batch.DECISIONS_PENDING (depth 2).

7. **Self-referential TransmissionFormat.supersedes_format_id** for the OCC-on-parent race scenario.

8. **Logical clock with fixed default `2026-08-01T00:00:00Z`** — drives deterministic cutoff, retention, and auto-decision tests via `/_clock/set_current_utc`.

9. **ECR (earnings credit rate) calculation** uses actual/360 day-count convention with bank-level default vs agreement-level override, plus cap-at-gross (bank never pays customer for excess ECR) — a real treasury billing concept that produces subtle reconciliation tests.

10. **Compound billing cycle settlement**: AnalysisCycle.DISPUTED state is entered via cascade when an ErrorCreditRequest is submitted; settle only proceeds once all disputes are resolved, and approved credits further reduce net_amount_due (which floors at 0).

## Step 3: Copy Shared Files — 2026-08-13T20:54:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1548_treasury_management_lockbox_services/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T21:20:23.000Z

PRD generation complete. Output: `/home/ubuntu/github/CodingPRD/tasks/task_1548_treasury_management_lockbox_services/workspace/PRD.md`

## Summary

**Line count:** 376 lines

**Sections:**
- §1 Introduction (2 paragraphs — business context + scope walk)
- §2 Global Specifications: 2.1 RBAC (8 roles, identity prose per role), 2.2 API Response Structure (byte-identical to the fixed verbatim block — verified programmatically), 2.3 Pagination, 2.4 Resource Identity/Timestamps/OCC, 2.5 Bank Posture & Logical Business Clock, 2.6 Nested Resource Addressing, 2.7 Monetary Precision/Rounding/Basis Points, 2.8 Segregation of Duties, 2.9 Validation Order (15-check priority list)
- §3 Business Logic (8 subsections, business-timeline grouping): 3.1 Bank provisioning/posture/day-close, 3.2 Customer onboarding & agreements, 3.3 Sites/schedules/formats, 3.4 Batch capture/balancing/items, 3.5 Exceptions & image retrieval, 3.6 Transmission & settlement posting, 3.7 Account analysis cycle close/settlement, 3.8 SLA incidents & error credits
- §4 Endpoint Definitions: 119 rows (4 columns: Method, Path, Description, Authorized Role(s))
- §5 Error Code Catalogue: 26 rows (2 columns)

**Coverage (all programmatically verified against SCAFFOLD.yaml):**
- Entities: 14/14 represented in prose
- State machines: 13/13 — all transitions, preconditions, and side effects rendered (all 50 state values backticked; one gap found and fixed: `FULFILLED` now named in the `REQUESTED → FULFILLED` pair)
- Calculations: 10/10 as precise natural-language formulas (no pseudocode, no fuzzy words — swept with regex)
- Endpoints: 119/119 rows; every scaffold path and method+path pair present
- Errors: 26/26 in §5 table and each id mentioned in §2/§3 prose
- Roles: 8/8 with exact spellings and identity semantics (CustomerOperator entity-backed, seven opaque)

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 99 required, 99 present, 0 missing
- endpoints[].input: 66 required, 66 present, 0 missing
- endpoints[].query_params: 0 required, 0 present, 0 missing
- path params: 14 required, 14 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 15 checked, 15 expressed as an explicit ordered list in §2.9, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write endpoint + expected_agreement_version/expected_cycle_version + ERR_STALE_VERSION/412 all named), 0 missing
- state_machines[].transitions: 60 checked, 60 fully expressed, 0 missing
- calculations[]: 10 checked, 10 fully expressed (variants, constants 360/10000/200bp/7yr/30d/2bd/1bd/10%, per-line-then-sum rounding, >=-threshold breach, at-cutoff rollover all in prose), 0 missing
- validations[] conditions: 15 checked, 15 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed in workflow narratives (cascades, auto-decision, expiry, ledger credit, incident emission, line-item emission), 0 missing
- entities[].fields[] structured content: defaults/initial values/computed derivations reconstructible from prose, 0 missing
- sibling-branch symmetry: parallel branches (LIVE vs SUSPENDED decommission, approve/partial/deny, PENDING vs ESCALATED decide/auto-decide) carry equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 493
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Zero-Silence Rule notes:**
- The scaffold's two batch-rejection paths are both rendered as written: at close, *any* `RETURNED`/`DECISIONED_RETURN` item sends the compound status to `REJECTED`; at day-close, a `READY_TO_SETTLE` batch whose items are *all* returns also goes `REJECTED`. Both rules stated verbatim-semantics without reconciliation.
- `ERR_EXCEPTION_ALREADY_DECIDED` and `ERR_AUTO_DECISION_IMMUTABLE` overlap in the catalog; both are expressed distinctly (wrong status vs. expired window).
- `ERR_INVALID_REQUEST` has no scaffold priority; it is presented as an independent malformed-body rejection without inventing an ordering position.
- The `balance` mismatch duality (transition to `OUT_OF_BALANCE` per the state machine + `ERR_BATCH_OUT_OF_BALANCE` per the validation table) is rendered with both scaffold facts intact.
- The withheld index files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced.

## Step 6: Generate Implementation — 2026-08-13T22:02:26.000Z

Implementation complete and verified. Summary:

## Files (in `/home/ubuntu/github/CodingPRD/tasks/task_1548_treasury_management_lockbox_services/workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | Launcher: `set -euo pipefail`, guarded `pip install` (only if `import flask` fails), `exec python3 app.py` in foreground |
| `requirements.txt` | 1 | `flask>=2.2` |
| `app.py` | 43 | Flask app, blueprint registration, envelope error handlers (ApiError, 404, 405, generic), `app.run(host="0.0.0.0", port=$PORT default 10000)` |
| `appobj.py` | 3 | Shared `Blueprint` |
| `store.py` | 27 | 14 empty in-memory dicts + logical clock + seq counter. **No seeding anywhere** |
| `util.py` | 257 | Envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`), `ApiError`, logical-clock timestamps (3-fractional-digit ISO Z), business-day math, `Decimal` ROUND_HALF_UP, body/field validators, pagination (`limit`/`offset`/`total_count`/`has_more`, default 10, min 1, max 100), created_at-asc sort |
| `helpers.py` | 515 | Auth (`X-User-ID`/`X-User-Role`, 8 roles), CustomerOperator ownership scoping, left-to-right nested path resolution, posture gate, derived `batch_status`, availability assignment, cycle open/finalize/SLA-recompute, line-item emission, exception decision application, business-day checkpoint |
| `routes_admin.py` | 517 | Bank lifecycle, clock, customers, agreements |
| `routes_sites.py` | 345 | Sites, availability schedules, transmission formats |
| `routes_batches.py` | 600 | Batches, items, exceptions, image requests |
| `routes_billing.py` | 323 | Cycles, line items, SLA incidents, error credits |
| `routes_flat.py` | 121 | 13 flat single GETs + 13 flat lists + 13 bank-scoped `*_index` lists (generated from a spec table) |

Total: 2,762 lines.

## Coverage

- **14 entities**: Bank, Customer, ServiceAgreement, LockboxSite, TransmissionFormat, RemittanceBatch, RemittanceItem, AvailabilitySchedule, ExceptionItem, ImageRetrievalRequest, AnalysisCycle, AnalysisLineItem, SLAIncident, ErrorCreditRequest — each a dict keyed by id with `id`/`created_at`/`updated_at`/`version` common fields (version increments on every mutation, cascades included).
- **12 state machines**: all transitions from §1.2 implemented, including bank suspend/resume/liquidate cascades (with per-source site suspension tracking), customer/agreement cascades, site go_live gating, format supersede cascade (bumps parent agreement version), dual capture×transmission batch dimensions plus derived compound status (OPEN/HELD/DECISIONS_PENDING/READY_TO_SETTLE/SETTLED/REJECTED), item disposition, exception DECIDED/AUTO_DECISIONED/ESCALATED (one-time +1 business day), image EXPIRED checkpoint, cycle FINALIZED/DISPUTED/SETTLED, incident CONFIRMED/REJECTED/CREDITED, credit APPROVED/PARTIALLY_APPROVED/DENIED.
- **10 calculations**: availability assignment (priority → effective_from DESC → created_at ASC, TWO_DAY fallback, on_capture vs on_exception_decision anchors), same-day credit, earnings credit (actual/360, bp/10000, floor 0, cap at gross, override honored only when `ecr_override_allowed`), gross service charges (per-line rounding then sum), net amount due (ECR → SLA → error credits, floored), average collected balance (accumulate daily, round only at divide, 0-days → 0), SLA error rate (`>=` threshold is breach, 10% credit), business-date rollover (cutoff `>=` rolls forward), exception auto-decision date (+2 business days at site cutoff), image retention (item created_at + 7 years).
- **119 endpoints**: all routes from the scaffold table, including the 13 flat GETs, 13 flat lists, 13 `*_index` lists, and `POST /_clock/set_current_utc`.
- **26 errors**: full catalog with exact IDs and HTTP statuses, enforced in PRD §2.9 priority order (auth → role → existence → posture → state → SoD → OCC → references → balance → site prereqs → retention → exception window → customer-active → blockers → uniqueness). Note: the `balance` mismatch path deliberately mutates to OUT_OF_BALANCE *and* returns 409 `ERR_BATCH_OUT_OF_BALANCE`, per PRD §3.4.

## Logical clock

Module-level `CLOCK` starts at `2026-08-01T00:00:00Z`, never reads wall time. `POST /_clock/set_current_utc` (BankOperationsAdmin) sets it. All `created_at`/`updated_at`/decision/fulfillment timestamps derive from it; each Bank's `current_business_date` (default 2026-08-01) advances only via `close_business_day`, which runs auto-decisions, image expiry (>30 days → EXPIRED + LATE_IMAGE_FULFILLMENT incident), ACKED-batch settlement with availability-weighted collected-balance accumulation, and per-ACTIVE-customer day counting.

## start.sh contract

Reads `PORT` (default 10000), binds `0.0.0.0`, foreground via `exec`, pip install guarded by an `import flask` probe so per-test reboots are no-ops. Verified: fresh boot → empty store, HTTP ready in ~2s, responds on the host's external interface.

## Verification

Four smoke suites run against live boots all pass: full happy path (bank→customer→agreement→site→schedule/format→batch→items→accept→balance→close→transmit→ack→settle) with exact availability/business-date assertions; exception decide/escalate/auto-decision/SoD/scoping; cycle finalization with exact ECR/SLA-credit/line-item figures (e.g. breach credit = rhu(5025×0.10)=503, avg balance rhu(1000/21)=48); dispute → partial approval → disputed settle net 4600; posture cascade blocking and resuming; image retention auto-DENY at 2033 and late-fulfillment incident emission.

## Step 5: Generate Unit Tests — 2026-08-13T22:07:34.000Z

All checks pass. Here is the final summary.

## Generation complete — task_1548_treasury_management_lockbox_services

### test_helpers/ (9 files)
- `/home/ubuntu/github/CodingPRD/tasks/task_1548_treasury_management_lockbox_services/test_helpers/__init__.py` — barrel export (framework + PRD-specific)
- `types.py` — 14 entity TypedDicts (all carry id/created_at/updated_at/version per PRD §2.4) + 18 enums
- `api_client.py` — `ApiClient(GenericApiClient)` with 86 methods covering every nested endpoint in PRD §4 plus `/_clock/set_current_utc`
- `api_errors.py` — 26 `ApiErrorId` values with HTTP map registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions + `assert_batch_balance_invariant` / `assert_net_amount_non_negative`
- `factories.py` — 12 payload factories (input fields only)
- `constants.py` — day-count basis 360, bp denominator 10000, SLA 10% rate, 7-year retention, 2026-08-01 defaults
- `test_users.py` — 8 role builders; `make_customer_operator_headers(customer_id)` for the entity-backed role
- `fixtures.py` — tiered composites: `setup_active_agreement`, `setup_live_lockbox` (with_format/with_schedule/go_live flags, multi-schedule specs), `add_live_customer_to_bank`, batch lifecycle (`create_batch`→`begin_capture`→`capture_item`→`accept_item`→`balance_batch_ok`→`close_batch`→`settle_batch`), `capture_and_accept_items` loop helper, exception/image/incident/credit helpers, `run_close_business_day` / `run_close_analysis_cycle` / `settle_cycle` (OCC reads fresh versions)

### test_suite/ (11 files)
`conftest.py` + `test_01` (banks/customers/envelope/pagination) · `test_02` (RBAC & posture) · `test_03` (agreement lifecycle & OCC) · `test_04` (site gates & format supersession) · `test_05` (batch intake & balancing) · `test_06` (availability assignment) · `test_07` (exceptions) · `test_08` (same-day credit & bank cascade) · `test_09` (image retention & references) · `test_10` (billing cycles & SLA)

### Test counts
- **Total: 59 tests** — Queue A: 34, Queue B: 25.

### Queue A: 17/18 instances with ≥2 tests
- **Skipped:** `Difficulty/resource_temporal_overlap/availability_schedule_overlapping_effective_windows_same_pattern_rejected` — fails the coverage condition: no PRD sentence rejects overlapping same-pattern schedules; PRD §3.3's tie-break chain ("any remaining tie breaks toward the schedule with the earlier `created_at`") contradicts the "rejected as ambiguous" assertion.

### Queue B: 25/25 non-stub instances with 1 test each; 6 `excluded_because` stubs not translated (all difficulty-instance pointers verified to resolve).

### Key adjudications (PRD-first)
1. **Go-live gates instance**: the recipe's DRAFT-agreement → `ERR_INVALID_STATE_TRANSITION` assertion is not uniquely derivable (PRD names no error for the parent-agreement gate, and a DRAFT agreement necessarily also lacks an ACTIVE format). Emitted the two uniquely-derivable gates instead: missing ACTIVE format → `ERR_SITE_LACKS_TRANSMISSION_FORMAT`; missing ACTIVE schedule → `ERR_SITE_LACKS_AVAILABILITY_SCHEDULE`.
2. **Exception SoD instance**: the recipe's literal trigger (CustomerOperator carrying the raiser's id) would fire `ERR_FORBIDDEN_FOR_ROLE` first (CustomerOperator is entity-backed, §2.1). Reconstructed: the raising LockboxOperator (opaque role) uses the customer's id as X-User-ID, so the customer-side decide carries the same X-User-ID → `ERR_SEGREGATION_OF_DUTIES`.
3. **Arithmetic corrections flagged by the design YAML's own comments**: gross total asserted as **33411** (PRD §3.7 counts `DECISIONED_PAY` in `accepted_item_count` → 5×7 capture fees, not the YAML's 3×7); SLA credit **10050**; ECR scenario uses 100000 maintenance so the min-cap doesn't bind.
4. **Date fixes**: PRD §2.5 pins `current_business_date`=2026-08-01 at bank creation regardless of the logical clock, so the before-cutoff and TWO_DAY-default tests advance via `close_business_day` to Monday 2026-08-03 to reach the asserted dates deterministically (2026-08-01 is a Saturday; business-day arithmetic verified).
5. **`err_stale_version_on_agreement_activate`**: emitted the instance's stated claim via create(v1)→implement(v2)→activate(expected=1) → `ERR_STALE_VERSION`, instead of the recipe's self-contradictory double-activate assert.

### Stage 2 self-check results
- Tag audit: 59/59 tests carry exactly one `Design:` tag; all tags resolve to real instance names; no tags point at stubs.
- PRD coverage: 93 citation fragments across all docstrings verbatim-match PRD.md (8-word-probe grep after whitespace normalization) — all pass after fixing two citations during the sweep.
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; gaps stay gaps.
- `pytest --collect-only` on the suite: 59 collected, 0 errors; `test_helpers` imports cleanly standalone.

## Step 7: Run Tests and Iterate — 2026-08-13T22:37:02.000Z

Clean sweep: all 8 rounds at 58/58 passed, 0 failed. The benchmark loop is complete.

## Summary

**Iterations run:** 3 sweeps (1 diagnostic + 2 fix iterations), 8 parallel rounds each.

**Tests deleted (1):**
- `test_02_rbac_and_posture.py::TestRoleAuthorization::test_customer_operator_identity_is_entity_backed` — unique-derivability collapse (PRD silence on error identity). PRD §2.1 defines the CustomerOperator ownership comparison and scoped reads but names no `error_id` for a failed cross-customer ownership check on a write; endpoint-level role authorization passes (CustomerOperator is allowed on the endpoint) and the path id exists in the bank, so both `ERR_FORBIDDEN_FOR_ROLE` (asserted) and `ERR_NOT_FOUND` (scoped-invisibility reading) are PRD-defensible — two faithful readers diverge. Scaffold driver: `Corner/rbac/customer_operator_identity_is_entity_backed` (role `identity: entity_backed:Customer` without a pinned error for ownership failure).

**test_helpers/ fixes:**
- `constants.py`: `PAYER_ROUTING` was "0710002880" (10 digits) → "071000288". PRD §3.4 verbatim requires "the payer's nine-digit ABA `payer_routing_number`", which the implementation correctly enforced — this single fixture bug caused 22 of the 30 initial failures ("Setup step failed: payer_routing_number must be a 9-digit ABA number").
- `fixtures.py`: added `run_close_analysis_cycle_at_month_end()` — advances the business date one business day at a time until every targeted OPEN cycle's `cycle_end_date` equals the bank's `current_business_date` (PRD §3.7's explicit finalization gate), then closes. The old fixture closed mid-month so cycles never reached FINALIZED.

**test_suite/ fixes:**
- `test_06` (3 sites) and `test_08` (2 sites): inline 10-digit routing literals → 9-digit, same PRD §3.4 payload violation as the constant.
- `test_04`: `_setup_two_formats(self)` → `(self, api)` plus both call sites — `NameError: api`.
- `test_10`: added missing `settle_cycle` import (latent `NameError` masked by the earlier FINALIZED failure); switched all 6 `run_close_analysis_cycle` call sites to the month-end helper; moved `report_incident` **before** the cycle close in `test_occ_analysis_cycle_settle` so §3.7's attach-at-finalization sets the incident's `cycle_id`, making §3.8's recompute-on-confirm (the OCC version bump) reachable; refreshed stale "1 day elapsed" comments to the 21-day arithmetic (assertions unchanged — ECR 100/300, gross 33411/100500, SLA 200/196bp are rounding-stable under month-end advancement).
- `test_03`: terminal-lockdown test closes the cycle at month-end via the new helper.

**implementation/ fixes:**
- `routes_admin.py::activate_agreement` and `helpers.py::finalize_cycle`: new OPEN cycles are created with `agreement_id=None`; the reference is stamped at close per PRD §3.7 ("the cycle's `agreement_id` references the `ACTIVE` agreement at close"). Previously the always-present OPEN cycle referenced the agreement from creation, permanently blocking agreement termination under §3.2's "every AnalysisCycle referencing it SETTLED" gate.
- `routes_admin.py::terminate_customer` and `liquidate_bank`: the all-cycles-SETTLED gate now skips in-flight OPEN cycles — a forced reading, since a fresh OPEN cycle always follows a close and the literal reading renders both PRD endpoints unreachable (§3.7 even notes a cycle can open and close the same day at termination).

**Final state:** 58/58 tests passing in every one of the 8 parallel rounds (verified via results.1..8.json).

## Step 8: Finalize PRD — 2026-08-13T23:00:00.000Z

PRD_FINALIZED.md is complete. Final report:

## Output
`/home/ubuntu/github/CodingPRD/tasks/task_1548_treasury_management_lockbox_services/workspace/PRD_FINALIZED.md` — 4 inline revisions, no new sections.

**Size:** PRD.md 376 lines / 56,676 chars → PRD_FINALIZED.md 376 lines / 58,179 chars. Line delta 0 (all edits inline); char delta +1,489 (+2.64%).

## Changes (one bullet per edit)
- **§2.1** — revise — pins that a CustomerOperator naming a resource owned by a different customer (nested path id, flat single read, or an otherwise-authorized write) gets `ERR_NOT_FOUND` (404), not `ERR_FORBIDDEN_FOR_ROLE`; flat/bank-scoped lists omit out-of-scope rows — `implementation/helpers.py:44-47` (`scope()` → `not_found`), `:61-67` (`R_customer`), `implementation/routes_batches.py:257`, `implementation/routes_flat.py:56-98`.
- **§3.1** — revise — liquidation gate changed from "every AnalysisCycle is `SETTLED`" to "every AnalysisCycle that has left `OPEN` is `SETTLED` — an in-flight `OPEN` cycle never blocks liquidation" — `implementation/routes_admin.py:132-137`.
- **§3.2** — revise — customer-termination gate changed from "all AnalysisCycles `SETTLED`" to "every AnalysisCycle that has left `OPEN` to be `SETTLED` — an in-flight `OPEN` cycle never blocks termination" (still `ERR_CUSTOMER_NOT_SETTLED`) — `implementation/routes_admin.py:334-342`.
- **§3.7** — revise — pins (i) not-due close is a silent no-op, not an error; (ii) `agreement_id` is empty while a cycle is `OPEN`, established at finalization, with fallback to the latest-created non-`TERMINATED` agreement and empty+zero-fee-rates when none exists; (iii) first cycle opens at first-agreement activation with `cycle_start_date` = that day's business date; (iv) cycles span calendar months (`cycle_end_date` = last day of start month) and each successor starts the calendar day after its predecessor's end — `implementation/routes_admin.py:152-182` (close gate/no-op), `:455-460` (first cycle at activation), `implementation/helpers.py:215-244` (month-end bounds), `:316-404` (finalize: agreement stamp + fallback + next-cycle open).

Step_7_diff items producing **no** PRD edit (verified against impl): the 10→9-digit `PAYER_ROUTING` fixes (constants.py, test_06, test_08) — pure fixture bugs; PRD §3.4 already pins "nine-digit ABA" and impl enforces `^\d{9}$` (`routes_batches.py:290-291`, `routes_admin.py:36-37`). test_04 `(self, api)` NameError and test_10 `settle_cycle` import — pure test bugs. test_10's `report_incident`-before-close reorder and comment refresh — attach-at-finalization (§3.7) and recompute-on-confirm (§3.8, `helpers.py:285-313`, `routes_billing.py:185-188`) were already PRD-pinned. test_03's month-end close — covered by the §3.7 edits above.

## Per-edit pre-edit search log
1. **§2.1 edit.** (a) Subject: error identity for CustomerOperator cross-customer access. (b) Enumerated: `helpers.py` `scope`/`R_customer`; all 24 `R_customer` callsites (uid/role-passing ones in `routes_admin.py:236,398,407`, `routes_billing.py:34,43,91,101,116,157,166,217,250,259`, `routes_sites.py:30,89,244,298`, `routes_batches.py:36,125,425,434,444,467,503,546,555`); explicit `scope` at `routes_batches.py:257`; `routes_flat.py` `_get_flat`/`_list_flat`/`_list_index`; `routes_admin.py:240-247` customer list filter; `routes_flat.py:23,41-47` availability-schedule customer-linkage absence; body-reference guards (`routes_billing.py:128-137,223-226`, `routes_batches.py:512-515`) which raise `ERR_INVALID_REFERENCE` and were left to §2.6. (c) Two adjustments: scoped the 404 claim to resources "owned by a different customer" (AvailabilitySchedules carry no `customer_id` and their flat single reads are deliberately unscoped), and confined the list-omission clause to flat/bank-scoped lists (nested lists under another customer's id 404 via `R_customer`, not omission).
2. **§3.1 edit.** (a) Subject: liquidation all-cycles-SETTLED gate. (b) Enumerated: `routes_admin.py:122-140`; the reachability chain (cycle created at activation `:460`, fresh cycle after every close `helpers.py:404`, TERMINATED customers' cycles can never finalize since `close_analysis_cycle` targets only ACTIVE `:170-171`); parallel gate `routes_admin.py:334-342`; §2.9 item 14 summary left untouched. (c) Chose "has left `OPEN`" predicate phrasing to mirror the impl test `status ∉ {SETTLED, OPEN}` exactly.
3. **§3.2 edit.** (a) Subject: customer-termination all-cycles-SETTLED gate. (b) Enumerated: `routes_admin.py:322-349` (ACTIVE precondition, agreements gate, cycle gate, image-request gate — the latter also raises `ERR_CUSTOMER_NOT_SETTLED`, matching the original sentence's coverage); interplay with `helpers.py:404` fresh-cycle invariant; agreement-termination gate `routes_admin.py:521-524` (keyed on `agreement_id`, made unambiguous by edit 4's empty-while-OPEN pin — deliberately not edited). (c) Kept `(otherwise ERR_CUSTOMER_NOT_SETTLED)` attached to the cycles clause only; used the same "has left `OPEN`" phrasing as §3.1 for parallelism.
4. **§3.7 edit.** (a) Subject: cycle lifecycle (first-open moment, bounds derivation, `agreement_id` stamping, not-due close). (b) Enumerated: `routes_admin.py:152-182`, `:431-461`; `helpers.py:208-212` (`open_cycle`), `:215-216` (`last_day_of_month`), `:219-244` (`open_new_cycle`), `:247-253` (`active_agreement_for`), `:316-404` (`finalize_cycle`); OPEN-cycle counter consumers (`routes_batches.py:358-361`, `helpers.py:431-443`, `routes_batches.py:578-581`); `routes_flat.py:29` `agreement_id` list filter; test_03 lockdown flow (agreement TERMINATED before close → fallback → finalize succeeds) and test_10's 21-day ECR arithmetic (2026-08-01 activation → 2026-08-31 month-end). (c) Four adjustments: strict-equality phrasing for the close gate (impl uses `!=`, so an overshot cycle is also left untouched); "the reference is established at finalization" rather than a universal "stamped with the ACTIVE agreement" (fallback can leave it empty); first-cycle opening scoped to the ONBOARDING→ACTIVE flip only (later activations open nothing); successor start described as "the day after" (calendar day, `timedelta(days=1)`), not business day.

## Step 9: Complete PRD — 2026-08-13T23:25:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1548_treasury_management_lockbox_services/workspace/PRD_COMPLETED.md` is written as a minimal patch over `PRD_FINALIZED.md`.

## Summary

- **Source vs output**: PRD_FINALIZED.md 376 lines / 57,864 chars → PRD_COMPLETED.md 378 lines / 62,877 chars (**+2 lines, +5,013 chars**). 28 edit sites, all inline inserts/revisions; no new sections.
- **Counts**: 21 ambiguity-pins, 7 mismatch-revisions.

### Changes (section — insert/revise — ambiguity/mismatch — what — impl ref)

1. §1 — revise — mismatch — "one-business-hour service level" → "one-hour" (impl adds a fixed 1 hour, no business-hour calendar) — routes_batches.py:529
2. §2.1 — insert — ambiguity — AvailabilitySchedules carry no `customer_id`: CustomerOperator flat/index schedule lists return empty; flat single-schedule reads unscoped — routes_flat.py:23-24, 41-47, 62-73
3. §2.2 — insert — ambiguity — unknown paths/unsupported methods → `ERR_NOT_FOUND` 404 in standard envelope — app.py:26-33
4. §2.3 — revise — ambiguity — `offset` must be non-negative; non-integer/out-of-range limit/offset → `ERR_INVALID_REQUEST`; sort ties break by persistence order — util.py:211-232
5. §2.4 — revise — ambiguity — `version` starts at 1 on creation — util.py:191-199
6. §2.5 — revise — ambiguity — enumerate posture-gate exemptions: bank provisioning/posture/liquidation, clock set, business-day close, analysis-cycle close, all reads; every other mutation requires OPERATING — routes_admin.py:74-197, helpers.py:140-143
7. §2.9 rule 5 — revise — mismatch — site-liveness (`ERR_SITE_NOT_LIVE`) checked right after posture and before resource state; `ERR_ITEM_NOT_IN_CAPTURED_STATE` and decide-time `ERR_EXCEPTION_ALREADY_DECIDED` classified at this step — routes_batches.py:155-158, 343-347, 449-451
8. §2.9 rule 12 — revise — mismatch — window error is `ERR_AUTO_DECISION_IMMUTABLE` (not ALREADY_DECIDED) — routes_batches.py:455-457
9. §3.1 — revise — ambiguity — bank ECR and SLA threshold are non-negative integers — routes_admin.py:38-41
10. §3.1 — revise — ambiguity — resume blocker: "unresolved" = still `CONFIRMED`, age measured `occurred_on_business_date` → `current_business_date` — routes_admin.py:102-106
11. §3.1 — insert — ambiguity — empty (zero-item) batch is never auto-REJECTED at day close — helpers.py:501-504
12. §3.2 — revise — mismatch — customer suspension holds batches with capture not yet closed (RECEIVED/CAPTURING/BALANCED/OUT_OF_BALANCE); resume restores only cascade-suspended agreements/sites; multi-cause sites return to LIVE only when all causes lift; resume releases held batches; agreement-resume customer gate is `ERR_CUSTOMER_NOT_ACTIVE`; termination blockers: surviving agreement/site → `ERR_INVALID_STATE_TRANSITION`, unsettled cycles → `ERR_CUSTOMER_NOT_SETTLED` — routes_admin.py:280-318, 331-333, 494-496, 518-524
13. §3.2 — revise — ambiguity — all four agreement fees and the ECR override are non-negative integers — routes_admin.py:364-369
14. §3.3 — revise — mismatch — SUSPENDED → LIVE path does not re-check schedule/format prerequisites (only agreement ACTIVE + customer ACTIVE + bank OPERATING); go-live clears all suspension causes and releases site batches — routes_sites.py:95-125
15. §3.3 — insert — ambiguity — decommission LIVE-path open-image-request blocker → `ERR_INVALID_STATE_TRANSITION` — routes_sites.py:155-159
16. §3.3 — revise — ambiguity — schedule pattern is 1–9 digits; `effective_to` < `effective_from` → `ERR_INVALID_REQUEST`; final tie-break is server persistence order — routes_sites.py:185-192, helpers.py:192-198
17. §3.3 — revise — ambiguity — format-retire PENDING check is agreement-wide (batches don't record their format); blocker → `ERR_INVALID_STATE_TRANSITION` — routes_sites.py:336-342
18. §3.4 — insert — ambiguity — `declared_item_count`/`declared_total_cents` non-negative — routes_batches.py:66-67
19. §3.4 — revise — ambiguity — item `amount_cents` positive; Return and Raise-exception gated only on item `CAPTURED`, not batch capture status — routes_batches.py:292, 365-378, 381-414
20. §3.4 — revise — mismatch — frozen `same_day_credit_cents` is a retained of-record figure; settlement accrues per-item by `availability_date`, not from it — helpers.py:497-500
21. §3.5 — insert — ambiguity — re-escalating an ESCALATED exception → `ERR_INVALID_STATE_TRANSITION` — routes_batches.py:470-471
22. §3.5 — revise — ambiguity — `requested_image_kinds` must be non-empty; retention = 7 calendar years (Feb 29 → Feb 28); `sla_due_at` = exactly +1 hour; `fulfillment_uri` is server-minted (fulfill takes no payload) — routes_batches.py:491-495, 507-510, 529, 573-576
23. §3.6 — revise — mismatch — transmit generates no payload and auto-raises no `LATE_TRANSMISSION` incident (manual filing only) — routes_batches.py:232-248
24. §3.6 — revise — mismatch — HELD arises only from bank/customer cascades (not agreement/site); hold is a single flag cleared by bank resume, customer resume, or site go-live; HELD blocks nothing by itself — helpers.py:154-161, routes_admin.py:83-91/109-118/285-289/315-318, routes_sites.py:121-124
25. §3.7 — revise — ambiguity — close_analysis_cycle: unresolvable `customer_id` → `ERR_NOT_FOUND`; multiple ACTIVE agreements → earliest-created — routes_admin.py:158-164, helpers.py:247-253
26. §3.7 — revise — ambiguity — `current_analysis_cycle_index` increments only when ≥1 cycle finalized; finalization zeroes customer accumulator/days/running average — routes_admin.py:179-180, helpers.py:396-399
27. §3.8 — revise — mismatch — system auto-raises only late-image-fulfillment and expired-image-request incidents (no auto late-transmission) — helpers.py:476-483, routes_batches.py:582-584
28. §3.8 — revise — mismatch+ambiguity — missing required incident reference → `ERR_INVALID_REQUEST` 400; confirm recompute applies to FINALIZED or DISPUTED cycles and adds/removes the SLA_CREDIT line plus net-due recompute; error credits fileable against FINALIZED or DISPUTED cycles (cascade only from FINALIZED; other statuses → `ERR_INVALID_STATE_TRANSITION`); `requested_credit_cents` positive; ruling a non-SUBMITTED request → `ERR_INVALID_STATE_TRANSITION` — routes_billing.py:123-126, 185-188, 220-228, 240-242, 264-266, helpers.py:285-313
29. §4 — revise — mismatch — `raise_exception` returns HTTP 200 (not 201) with the created ExceptionItem — routes_batches.py:414

Key mismatches eliminated: the phantom auto-`LATE_TRANSMISSION` incident and payload generation, the "business hour" SLA, agreement/site cascades holding batches, the SUSPENDED-path go-live re-checking prerequisites, and FINALIZED-only error-credit filing.
