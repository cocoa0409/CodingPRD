# Worklog — task_2399_mail_order_contact_lens_prescription

## Step 1: Create task directory — 2026-09-02T00:00:00.000Z

Created `tasks/task_2399_mail_order_contact_lens_prescription/` and `tasks/task_2399_mail_order_contact_lens_prescription/workspace/` (pre-allocated name used verbatim; no index scan performed).

## Step 2: Generate scaffold — 2026-09-02T08:38:10.000Z

Done. All three artifacts are written and the lint is clean.

**Verdict block (verbatim):**

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2399_mail_order_contact_lens_prescription/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2399_mail_order_contact_lens_prescription/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2399_mail_order_contact_lens_prescription/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    66
  §1.1 entities declared:     14
  §1.8 instances scanned:     27
  §1.9 instances scanned:     68
  Calls scanned (§1.8+§1.9):  801

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2399_mail_order_contact_lens_prescription/`):
- `SCAFFOLD.yaml` — 2851 lines, §1.0–§1.7 only (no design keys present)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2932 lines, single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — 3759 lines, single key `scaffold_corner_design`

**Scaffold surface (deliberately above the expert band, `difficulty_level: expert_plus`):**
- 14 entities: InsurancePlan, Product, LensEquivalence, Prescriber, Customer, Prescription, VerificationRequest, Order, ReorderHold, AutoReorderSchedule, ReturnRequest, ReimbursementClaim, PrescriberDispute, ComplianceEvent (append-only)
- 66 endpoints, 49 error codes, 39 priority-ordered validations, 9 state machines (Order carries two independent dimensions: `verification_state` × `fulfillment_state`), 7 calculations, 2 OCC concurrency rules, 5 roles under a segregation-of-duties model
- Calculations: order total with free-shipping threshold, integer-hundredths weighted `parameter_deviation_index`, business-hour passive verification deadline (8h directory-verified / 12h self-reported / 4h contact cooldown), three-variant return settlement (per-box vs pooled rounding vs torn-lens cap), eight-step out-of-network reimbursement with tiered processing fee, dual-variant auto-reorder cadence, plan-year allowance aggregation
- Complexity layers: `optimistic_concurrency`, `cascading_side_effects`, `dual_variant_calculation`, `scheduled_actions`, `derived_field_reconciliation`

**Design instance counts:**
- §1.8: 27 instances across all 9 difficulty rules (3/3/3/2/3/4/3/3/3)
- §1.9: 85 instances across all 9 guide sections — 68 full recipes + 17 `excluded_because` stubs (entities 15, state_machines 16, calculations 12, validations 10, endpoints 7, errors 10, rbac 7, cross_cutting_complexity_layers 6, consistency_model 2)

**Verified beyond the lint:** every `${var}` is bound before use in all 95 recipes; all 17 stub `difficulty_instance` references resolve by name into §1.8; no instance carries both `test_recipe` and `excluded_because`; all 85+27 names unique across the two files; and all 49 declared error codes are exercised by at least one design instance.

**Fixes applied to `SCAFFOLD.yaml` during the §1.9 audit pass** (the §1.5 iteration the skill asks for): removed `ERR_LENS_EQUIVALENCE_NOT_FOUND`, which no endpoint could trigger (49 codes remain); clarified validations 12, 31 and 37 so that on `POST /fulfillment/auto-reorder-run` they are evaluated per due schedule and cause a skip rather than an error response (previously ambiguous against the endpoint's declared skip semantics); renamed complexity layer `scheduled_deferred_actions` to the guide's vocabulary `scheduled_actions`.

## Step 3: Copy shared files — 2026-09-02T08:38:10.000Z

Copied `INSTRUCTION.md` → `tasks/task_2399_mail_order_contact_lens_prescription/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T08:52:30.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2399_mail_order_contact_lens_prescription/workspace/PRD.md` (500 lines).

**Sections written**

- §1 Introduction — 3 paragraphs framing the passive-verification spine, the commercial mechanics around it, and the two cross-cutting themes (derived ledgers, segregation of duties).
- §2 Global Specifications — 11 subsections: 2.1 RBAC (`X-User-ID` / `X-User-Role`, all 5 roles with entity-backed vs opaque identity semantics), 2.2 API Response Structure (pasted verbatim from `section-2.2-response-structure.md`), 2.3 Pagination and List Ordering, 2.4 Common Resource Properties and Snapshot Discipline, 2.5 The Logical Clock and Business-Hour Arithmetic, 2.6 Money in Whole Cents and Rounding Discipline, 2.7 Derived Ledgers and Reconciliation Invariants, 2.8 Segregation of Duties, 2.9 Optimistic Concurrency, 2.10 Request Evaluation Order (full 39-step precedence chain), 2.11 Cascade Discipline and the Compliance Trail.
- §3 Business Logic & Workflows — 9 subsections: reference data; patient records and capture; the submit fork and verification rounds; responses, sweep and expiry; ordering and pricing; substitution; fulfillment, holds and auto-reorder; returns and settlement; reimbursement, disputes and cascades.
- §4 Endpoint Definitions — 1 intro paragraph plus a 4-column table of all 66 endpoints.
- §5 Error Code Catalogue — 2-column table, 49 error IDs. Document ends here (no audit footer).

**Coverage audit results** (mechanical, scripted against SCAFFOLD.yaml)

```
Field coverage check:
- entities[].fields: 121 required, 121 present, 0 missing
- endpoints[].request_body / input: 80 required, 80 present, 0 missing
- endpoints[].query_params: declared inline within `input` (no separate key); all filter keys covered by the 80 above, 0 missing
- endpoints[].output keys: 20 required, 20 present, 0 missing
- path_params: only `id`, present
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 39 checked, 39 expressed in prose (full precedence chain in §2.10), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write action + expected_order_version / expected_prescription_version + ERR_STALE_ORDER_VERSION / ERR_STALE_PRESCRIPTION_VERSION all named), 0 missing
- state_machines[].transitions: 41 checked across 8 machines, 41 fully expressed, 0 missing
- calculations[]: 7 checked, 7 fully expressed; 28 named constants verified present by value, 0 missing
- validations[] conditions: 39 checked, 39 matchable to their error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: expressed, 0 missing
- entities[].fields[] structured content: 121 checked (all enum members, defaults, ranges, initial values, computed formulas), 0 missing
- sibling-branch symmetry: 7 groups checked (submit fork, 3 response types, 3 settlement modes, 2 cadence bases, 3 deviation bands, 3 fee tiers, upheld/dismissed), equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 797
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
- unbackticked path-shaped strings: 0
Status: PASS
```

**Notes on two deliberate judgement calls**, both resolved in favour of the more granular scaffold authority:

1. The scaffold's validation text says "X-Role"; the PRD uses the contract-mandated `X-User-Role` throughout.
2. `state_machines` attaches the supersession cascade (invalidate the superseded prescription, cancel its `ACTIVE` schedules) only to the `DRAFT → VERIFIED_ACTIVE` upload branch of submit, while the endpoint's own `side_effects` phrases it unconditionally. The PRD follows the state machine and states explicitly that the passive branch appends only the audit event — the asymmetry is written as intentional so an implementer cannot read it as an omission.

## Step 5: Generate unit tests — 2026-09-02T09:30:00.000Z

Generation complete for `task_2399_mail_order_contact_lens_prescription`.

## Files written (10,944 lines total)

**Stage 1 — `test_helpers/`** (9 files)
`__init__.py` (single import surface, re-exports the 17 framework generics), `types.py` (UserRole + ~31 status enums + TypedDicts for all 14 entities; `ComplianceEvent` deliberately lacks `updated_at`/`version`), `api_client.py` (`ApiClient` with all 66 PRD endpoints), `api_errors.py` (50-member `ApiErrorId` + `HTTP_STATUS_CODES`, registered via `set_error_http_status_map` at import), `constants.py`, `test_users.py` (entity-backed `make_customer_headers`/`make_prescriber_headers`; opaque `CO_ALPHA`/`CO_BRAVO`/`FO_ONE`/`ADMIN_ROOT`), `factories.py`, `assertions.py`, `fixtures.py` (~50 primitives + 24 composites).

**Stage 2 — `test_suite/`** (`conftest.py` + `test_01_`…`test_18_`)

## Test counts
18 test files, **148 test functions / 160 collected cases**.
Queue A (difficulty): 70 tests across files 01–09. Queue B (corner): 78 tests across files 10–18.

## Instances translated vs skipped
- **Queue A: 27/27 instances translated, 0 skipped**, every instance >=2 tests.
- **Queue B: 68/68 non-stub instances translated, 0 skipped**, every instance >=1 test.
- All 17 `excluded_because:` stubs correctly left untranslated; all 17 `difficulty_instance:` cross-references resolve to real difficulty instances (format is `rule_id / instance_name` — no broken pointers).

## Coverage audit
Clean on every gate: exactly one `Design:` line per test as the final docstring line; zero tags pointing at nonexistent instances or at stubs; zero dual-tagged/untagged tests; zero non-verbatim PRD quotes (whitespace-normalised grep of `workspace/PRD.md`); zero forbidden vocabulary (no "scaffold" / design-yaml / `test_recipe` / scaffold-section references) in either directory; `pytest --collect-only` and pyflakes both clean.

## Design-yaml bugs found (handled without weakening any translated instance)
1. Two recipes manually invalidate a prescription from `PENDING_VERIFICATION` / `VERIFIED_ACTIVE`, but §3.4 allows manual invalidation only from `CORRECTION_PENDING` — state rebuilt legally via DOCTOR_LOOKUP → round → CORRECTED → invalidate (`Corner/errors/invalidated_prescription_blocks_a_new_order_with_409`, `Corner/rbac/compliance_officer_performs_all_of_its_exclusive_operations`).
2. Three recipes assert `auto_reorder_enabled true` with zero schedules, contradicting §2.7's `schedules > 0 and holds == 0` definition — two dropped the sub-assertion, one added a PRD-legal ACTIVE schedule so the stated outcome holds.
3. `Corner/errors/substitution_without_an_active_mapping...` asserts `parameter_deviation_index null` where §3.5 says it "starts at 0.00" — sub-assertion omitted.
4. `Corner/rbac/return_settlement_requires_a_different_officer_than_the_approver` asserts an `APPROVED` return status the PRD never names — replaced with PRD-named observables (`approved_by_user_id`, null `settled_by_user_id`, frozen `settlement_cents`, terminal `SETTLED`).
5. `Difficulty/transitive_cascade/expiry_sweep_cascades...` asserts `HOLD_OPENED`/`SCHEDULE_PAUSED` events and intra-step `occurred_at` ordering the PRD attaches to other paths / never orders — those sub-assertions dropped.
6. Recipes throughout filter the compliance trail by `event_type`, a query parameter the PRD never declares (§2.3/§4 give only `limit`/`offset`) — `fixtures.compliance_events` reads the unfiltered trail and counts client-side, so no test depends on an undeclared filter.

## Step 6: Generate implementation — 2026-09-02T09:30:00.000Z

The implementation is complete and verified booting.

## Files written
`workspace/implementation/` — 21 files, 3,260 lines total: `start.sh` (16), `app.py` (56), `requirements.txt` (1), `db.py` (87), `errors.py` (68), `response.py` (75), `middleware.py` (281), `services/` (calc, ledger, events, workflow, __init__ — 728), `routes/` (8 blueprints + __init__ — 1,948).

## Endpoints
**66 routes — an exact 1:1 match with the 66 endpoints declared in `SCAFFOLD.yaml`** (verified by diffing the Flask url_map against the scaffold's method/path pairs).

## Notable design decisions
- **PRD wins over SCAFFOLD** on auth headers (`X-User-ID`/`X-User-Role`, not `X-Role`).
- **Uniform validation order per handler**, driven by PRD §2.10's 39-step list: identity → body/query parse → role → path 404s → body FK 404s → ownership → SoD → OCC → state → numbered business rules. SoD is checked *before* the state check on hold release and return settle; `ERR_PRESCRIPTION_NOT_VERIFIED` before `ERR_HOLD_OPEN_BLOCKS_ACTION`.
- **Substitution order** deviation-ceiling → consent → mapping existence → inactive; substitution is price-neutral.
- **Overlap check and supersession cascade attached to the UPLOAD submit branch only.**
- **All ledgers derived**, never incremented; `GET /customers/{id}/ledger` recomputes at read time without mutating.
- Money in integer cents via `Decimal` + `ROUND_HALF_UP`; deviation index in integer hundredths.
- Entity-backed roles get row-scoped list results (no 403 on collections), 403 `ERR_IDENTITY_MISMATCH` on single-row access.
- **No seeding, no disk**: every dict starts empty, clock defaults to `2026-08-01T00:00:00Z`.

## Boot confirmation
`python3 -m compileall` clean; `import app` clean. Booted repeatedly from a fresh process via `./start.sh`; each fresh boot returns `total_count: 0` for every collection and the default clock. Four end-to-end smoke scripts passed against clean boots (verification round/cooldown/CORRECTED/CONFIRMED; substitution + OCC 412; passive sweep expiry cascade; auto-reorder run; return proration cap + SoD-blocked settle; claim 8-step money; dispute-upheld cascade; 401/403/404/409/412/422/429 error shapes).

## Step 7: Run tests and iterate — 2026-09-02T11:40:00.000Z

The task is complete — the artifact was already fully green.

**Iterations run: 1** (one full 8-round parallel stability sweep, `--isolation per-test-server`, launched under `setsid nohup`, all 8 rounds joined with `wait`).

**Result: all 8 rounds passed 160/160** (148 test functions / 160 collected cases, 0 failed, 0 errors, 0 skipped). Round wall time ~1450s each; no flakiness surfaced across the 8 concurrent rounds, and the sweep log contained zero `FAILED` lines from any round.

| Round | passed / total |
|---|---|
| 1–8 | 160 / 160 each |

**Tests deleted:** none. No test failed in any round, so no test entered the diagnostic protocol and no PRD-silence / unique-derivability deletion was warranted.

**Fixes applied to `test_helpers/`:** none required.

**Fixes applied to `workspace/implementation/`:** none required.

Notes on the artifact state verified along the way:
- `workspace/implementation/start.sh` boots a fresh process per test (`exec python3 app.py`, `PORT` from env), and the implementation is documented and confirmed to hold all state in-memory with no seeding and no disk persistence — consistent with the per-test-server isolation contract.
- The worklog records that the test generator had already caught and neutralised six design-yaml/scaffold bugs at generation time (e.g. manual invalidation only legal from `CORRECTION_PENDING`, `auto_reorder_enabled` requiring `active_schedule_count > 0`, no undeclared `event_type` query filter on the compliance trail), which is the most likely reason this artifact came in clean on the first sweep.

**Orchestrator note (deviation recorded per AUTONOMY):** the Step 7 subagent deleted the `results.*.json` and `sweep.log` sweep artifacts on exit as a tidiness measure, but the skill's Output manifest requires `workspace/implementation/results.{1..8}.json` to persist as the evidence of the final green sweep. The orchestrator therefore relaunched an identical 8-round `setsid nohup` sweep purely to regenerate those artifacts, and ran Step 9 concurrently with it (Step 9 only reads `PRD.md`/`implementation/`/`test_*` and writes `PRD_COMPLETED.md`, so it cannot interfere with, nor be affected by, a read-only-to-it test sweep). No source file was modified between the green sweep and the regeneration sweep.

**Step 8: SKIPPED** — Step 7's skip condition is met exactly: exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes and 0 `implementation/` fixes. `PRD.md` already determined every behavior the implementation exhibits at every site Step 7 exercised, so there is no `<step_7_diff>` to patch and no `PRD_FINALIZED.md` is produced. Step 9 therefore starts from `PRD.md`.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-09-02T13:20:00.000Z

Done. `PRD_COMPLETED.md` written; nothing under `implementation/`, `test_suite/` or `test_helpers/` was touched. Source was `PRD.md` (Step 8 skipped, so no `PRD_FINALIZED.md`).

## Counts

- **PRD.md**: 500 lines, 82,350 chars → **PRD_COMPLETED.md**: 502 lines, 97,053 chars (**+14,703 chars**, +2 lines — both from two extra bullets appended to the existing §2.2 error-format bullet list; no new sections, no new paragraphs).
- **45 changed line-hunks** carrying **48 distinct changes**: **41 ambiguity-pins**, **7 mismatch-revisions**.

## Changes

- §2.1 — revise — ambiguity — prescriber ownership also gates reads of the prescriber row / verification requests / disputes, and passes when the row's prescriber FK is null — `middleware.py:61`, `reference.py:330`
- §2.1 — insert — ambiguity — list endpoints apply entity-backed ownership as a silent scope filter, not `ERR_IDENTITY_MISMATCH` — `prescriptions.py:162`, `orders.py:100`
- §2.2 — insert — ambiguity — `message` wording not contractual; `api_request_timestamp` is wall-clock; non-object/unparseable body → `ERR_INVALID_REQUEST`; undeclared body/query fields ignored; unrouted path → `ERR_NOT_FOUND` 404; bad method → `ERR_INVALID_REQUEST` at HTTP 405 — `response.py:36`, `middleware.py:80`, `app.py:30`
- §2.3 — revise — ambiguity — `created_at` ties broken by insertion order (common, since `created_at` is logical-clock); compliance-event trail accepts `event_type`/`subject_type` filters — `db.py:66`, `prescriptions.py:293`
- §2.4 — revise — ambiguity — `created_at`/`updated_at` read the logical clock, not wall clock — `db.py:72`
- §2.4 — insert — ambiguity — date-only fields serialize as bare `YYYY-MM-DD` — `response.py:46`
- §2.5 — revise — ambiguity — clock read/write both answer `data` = `{current_utc}` only; accepted `current_utc` formats (Z / offset / naive-as-UTC) — `reference.py:46`, `middleware.py:134`
- §2.6 — revise — **mismatch** — two-decimal fields are quantized (half-up) on input and emitted as JSON *numbers*, so `0.50` appears as `0.5`; PRD had claimed exact two-decimal presentation — `middleware.py:121`, `response.py:41`
- §2.7 — revise — ambiguity — `store_credit_cents` is derived (sum of SETTLED/STORE_CREDIT settlements), not incremented — `ledger.py:48`
- §2.7 — revise — ambiguity — plan-year anchor falls back to `01-01` for a customer with no plan — `ledger.py:20`
- §2.11 — revise — ambiguity — exact `subject_type` domain; `detail` null unless named; events appended only where named (cascade holds emit no `HOLD_OPENED`; cancellation-voided claims emit no `CLAIM_VOIDED`); `created_at` == `occurred_at` — `events.py:19`, `workflow.py:152`, `workflow.py:183`
- §3.1 — insert — ambiguity — all four reference entities accept `status` in the registration body — `reference.py:73,154,240,300`
- §3.1 — revise — ambiguity — `sphere_max < sphere_min` → `ERR_INVALID_REQUEST`, evaluated *after* the role check; `sphere_min`/`sphere_max` never enforced downstream; `material_family` required — `reference.py:153,158`
- §3.1 — revise — ambiguity — equivalence self-edges and parallel edges allowed, earliest-created `ACTIVE` edge governs; `to_product_id` → `ERR_PRODUCT_NOT_FOUND` — `reference.py:245`, `orders.py:117`
- §3.1 — revise — ambiguity — `license_state` length unvalidated; licence uniqueness is exact case-sensitive `(number, state)` — `reference.py:297,304`
- §3.2 — revise — ambiguity — `state_code` length unvalidated; email compared case-sensitively; plan-not-found precedes duplicate-email — `reference.py:385`
- §3.2 — insert — ambiguity — capture evidence fields may be supplied under any mode; `product_id` need not be `ACTIVE`; clinical decimals unbounded; `supersedes_prescription_id` must resolve — `prescriptions.py:97,105`
- §3.3 — revise — ambiguity — `RX_SUBMITTED` subject is the prescription; supersession invalidates from *any* status and is silent (no `RX_INVALIDATED`/`SCHEDULE_PAUSED`, no hold, orders untouched) — `workflow.py:135`
- §3.3 — revise — ambiguity — round-opening answers the new verification request at 201; `REQUEST_SENT` subject is the request — `prescriptions.py:284,287`
- §3.4 — revise — ambiguity — `CONFIRMED` promotes whatever status the prescription holds; `RESPONSE_RECEIVED` subject is the request; all three branches answer the request row — `verification.py:99`
- §3.4 — revise — ambiguity — corrected spheres quantized; `note` never persisted; corrected spheres ignored on other branches — `verification.py:114`
- §3.4 — revise — **mismatch** — denial blocks every `PENDING` order, from `RX_CLEARED` as well as `RX_PENDING` (PRD said only `RX_PENDING`); cascade hold emits no `HOLD_OPENED`; `ORDER_BLOCKED` detail null — `workflow.py:101`
- §3.4 — revise — **mismatch** — manual invalidate's hold records the *acting officer* in `opened_by_user_id`, not `system`; `reason` not persisted; no order/schedule effects — `prescriptions.py:325`
- §3.4 — revise — ambiguity — sweep step one visits SENT requests in `created_at` order, reports every timeout, and promotes nothing when the prescription left `PENDING_VERIFICATION` — `workflow.py:230`
- §3.4 — revise — **mismatch** — sweep step two pauses schedules *without* `SCHEDULE_PAUSED` events (unlike denial) though they still count; cascade hold emits no `HOLD_OPENED`; due prescriptions in `created_at` order — `workflow.py:164`
- §3.4 — revise — ambiguity — `holds_opened_count` is one per step-two expiry; the five members are the whole `data` — `workflow.py:260`
- §3.5 — revise — ambiguity — zero box sum → `ERR_INVALID_REQUEST` at step 2 — `orders.py:47`
- §3.5 — revise — ambiguity — expiry test precedes all three placement gates; any non-expired prescription status may be ordered against — `orders.py:54`
- §3.6 — revise — ambiguity — substitution examines neither order lifecycle dimension (SHIPPED/DELIVERED/CANCELLED all substitutable); `patient_consent` defaults false; repeats recompute from `ordered_product_id`; `SUBSTITUTION_APPLIED` subject is the Order — `orders.py:127`, `orders.py:150`
- §3.7 — revise — ambiguity — cancellation voids claims in `created_at` order with `CUSTOMER_REQUEST` regardless of `cancellation_reason`; `ORDER_CANCELLED` appended last; no `CLAIM_VOIDED` events — `workflow.py:176`
- §3.7 — revise — ambiguity — hold creation does not relate `customer_id` to `prescription_id`; `HOLD_OPENED` subject is the hold — `fulfillment.py:49`
- §3.7 — revise — **mismatch** — release `note` is accepted and discarded; escalation shares *none* of release's three gates — `fulfillment.py:95`, `fulfillment.py:118`
- §3.7 — revise — ambiguity — `observed_days_per_box` ≥ 1, absent under `USAGE_ADJUSTED` → `ERR_INVALID_REQUEST`; stored-but-ignored under `NOMINAL`; schedule product unrelated to prescription product — `fulfillment.py:150,153`
- §3.7 — revise — **mismatch** — resume evaluates `ERR_PRESCRIPTION_NOT_VERIFIED` *before* `ERR_HOLD_OPEN_BLOCKS_ACTION` (PRD prose had them reversed); `next_run_at`/`cadence_days` untouched — `fulfillment.py:248`
- §3.7 — revise — ambiguity — run's order carries `boxes_od` = `boxes_per_run`, `boxes_os` = 0, no receipt, no compliance event; expiry strictly after today; `next_run_at` advances from its own prior value; one processing per run — `workflow.py:299`, `workflow.py:319`
- §3.8 — insert — ambiguity — a return may be opened against an order in any `fulfillment_state` — `returns.py:56`
- §3.8 — revise — ambiguity — `torn_lens_count` absent under `TORN_LENS` → `ERR_INVALID_REQUEST`; optional and still checked under other reasons; quantity checks in listed order — `returns.py:53,64`
- §3.8 — revise — **mismatch** — return `status` includes `APPROVED` (PRD listed only `SUBMITTED`/`REJECTED`/`SETTLED`); approval also refreezes `settlement_channel`; `rejection_reason` required; no compliance events — `returns.py:141`
- §3.8 — revise — ambiguity — settle declared only from `APPROVED`, ignores order state, SoD precedes the state check, prior-settlement sum excludes self — `returns.py:170`
- §3.8 — revise — ambiguity — `refund_offset_cents` set on DRAFT claims in `created_at` order to the full settled sum — `returns.py:182`
- §3.9 — insert — ambiguity — claim creation ignores order `fulfillment_state` and does not require the plan be the customer's own; `packet_reference`/`submitted_at`/`voided_reason` null — `claims.py:52`
- §3.9 — revise — ambiguity — claim window counted in whole calendar days with an inclusive boundary — `claims.py:33`
- §3.9 — revise — ambiguity — `packet_reference` is `PKT-` + 12 upper-case hex; generation appends no event — `claims.py:147`
- §3.9 — revise — ambiguity — void leaves money fields standing; `CLAIM_VOIDED` subject is the claim, filed against the order's prescription — `claims.py:180`
- §3.9 — revise — ambiguity — disputes may be filed against a prescription in any status, several open at once; `DISPUTE_FILED` subject is the dispute — `disputes.py:44`
- §3.9 — revise — ambiguity — resolve sets `status` to the resolution value; `DISPUTE_RESOLVED` appended *after* the whole upheld cascade — `disputes.py:108,116`
- §3.9 — revise — ambiguity — upheld cascade invalidates from any status, appends no `ORDER_CANCELLED`, skips already-`CANCELLED` orders, opens no hold and pauses no schedule — `workflow.py:189`
- §3.9 — revise — ambiguity — reconciliation covers every distinct touched-order customer plus the prescription's own — `workflow.py:213`

## Orchestrator verification of the regeneration sweep

The `results.{1..8}.json` regeneration sweep launched alongside Step 9 completed while Step 9 was running and is independently green: **all 8 rounds 160/160 passed, 0 failed, 0 errors**, and `workspace/sweep.log` contains zero `FAILED` lines. Per-round duration ~385s. Both green sweeps ran against byte-identical `implementation/`, `test_suite/` and `test_helpers/` trees, so the pipeline's final state is confirmed twice over. Artifacts now persist at `workspace/implementation/results.{1..8}.json` and `workspace/sweep.log`.

## Pipeline complete

`workspace/PRD_COMPLETED.md` is written. Steps 1–7 and 9 all ran; Step 8 was skipped under its declared skip condition.
