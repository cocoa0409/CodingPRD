# Worklog — task_0921_naturopathic_functional_medicine

Scenario (verbatim from user):
> generate task hard than expert level! 921. Naturopathic & Functional-Medicine Practice: intake & extended history, functional lab panel & interpretation, protocol & supplement plan/dispensary, membership/package & visit, telehealth & messaging, insurance vs cash & superbill, follow-up & titration, referral

## Step 1: Create task directory — 2026-08-03T17:28:13.986Z

Created `tasks/task_0921_naturopathic_functional_medicine/` and `workspace/`. Index 0921 (highest existing was 0920).

## Step 2: Generate scaffold — 2026-08-03T18:33:56.000Z

Scaffold generated, validated, and lint-clean.

## Files

| Path | Lines |
|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_0921_naturopathic_functional_medicine/SCAFFOLD.yaml` | 2910 |
| `/home/ubuntu/github/CodingPRD/tasks/task_0921_naturopathic_functional_medicine/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2180 |
| `/home/ubuntu/github/CodingPRD/tasks/task_0921_naturopathic_functional_medicine/SCAFFOLD_CORNER_DESIGN.yaml` | 2560 |

## Metrics

- **Entities: 15** (flat topology, `api_prefix: ""`): Practitioner, Patient, IntakeSection, Membership, LabOrder, LabResult, Protocol, ProtocolItem, DispensaryProduct, ProductLot, Dispense, Encounter, MessageThread, Superbill, Referral
- **Endpoints: 68** (26 GET) · **Error codes: 34** · **Roles: 7** (segregation_of_duties model) · **Ladder rungs: 28**
- **State machines: 11 entities / 13 axis declarations / 75 transitions.** Non-linear: **Patient** (two independent axes + review re-open cycles), **Encounter** (two independent axes), **IntakeSection** (re-attestation cycle), **Membership** (pause/resume cycle + ACTIVE→ACTIVE roll self-loop), **LabOrder** (branch-with-revert on wash-out hold + critical diversion), **Protocol** (three-way terminal fan-out with divergent side-effect sets), **ProtocolItem** (hold/resume cycle), **MessageThread** (answer/reply cycle), **Superbill** (void/reissue cycle), **Referral** (decline/re-refer cycle → abandon)
- **Calculations: 9, of which 6 carry variants**; the 4+ genuine dual-variant forks are intake booking-vs-protocol scoring, standard-vs-functional analyte bands, retail/member/practitioner-cost pricing, entitlement-first vs cash-fallback settlement, plus the titration **anchoring fork** (re-anchor on decision vs preserve original anchor). Combinatorial modes are all three: (b) pinned per-unit rounding, (a) ceiling+branch extended-visit fee, (c) pinned 10-step proration order.
- **OCC rules: 3** (Patient←protocol create, Protocol←dispense, Membership←tier change) · **Conservation invariants: 4** (visit units, lab-credit units, lot units, patient cash ledger) · **Max cascade depth: 5** (critical analyte → LabOrder → RED_FLAG_AUTO Referral → Patient gate → Protocol.advancement_blocked → ProtocolItem.titration_locked; and the mirrored 5-link unfreeze on acknowledge; plus a depth-4 adverse-reaction stop-and-reverse from a different trigger)
- **Design devices**: global write-gate at rung 6 pre-empting payload-shape (rung 11) with explicit gated/not-gated endpoint lists; deliberately opposite interval geometries (half-open practitioner windows w/ telehealth-only buffer vs closed membership cycles; closed standard range vs half-open functional range on the *same* analyte; closed wash-out lower bound; closed cycle-day window)
- §1.8: **24 instances** across all 9 rule_ids (≥2 each). §1.9: **43 active instances + 10 `excluded_because` stubs** across all nine guide sections.

## Self-checks

- **A (incremental writes)**: all three files authored in bounded chunks and concatenated — no oversized single write.
- **B (YAML)**: all three `yaml.safe_load` cleanly. Two real parse failures found and fixed: trailing-`?` optional fields inside flow sequences (`input: [npi?, …]` — 25 lines requoted) and `$.data[0].version` JSONPaths inside flow mappings (2 quoted).
- **C (constants)**: **48 declared constants**, every one with an explicit scalar value (added flattened aliases `MEMBERSHIP_TIER_*_DISCOUNT_PCT` and `LAB_PANEL_*_WASHOUT_DAYS` so no calculation references a name without its own value). Automated sweep of every underscored ALL_CAPS token: the sole residual is `ERR_XXX`, the verbatim §1.0 response-envelope placeholder. All other ALL_CAPS tokens verified as enum members (incl. a new `request_enums:` block declaring the body-only enums: scope-review outcome, superbill action, referral action, severity, system discontinue reasons), error codes, or state names.
- **D (reachability)**: automated check — **0 unreachable states across all 13 axes; 0 enum values without a producing state**. Three defects found and fixed: (1) `Encounter.billing_status` listed `SUPERBILLED` as terminal while the superbill VOID transition leaves it — removed from `terminal_states`; (2) `MessageThread` had no OPEN→OPEN transition, so a patient message on an unanswered thread (needed to reach the 4-message e-visit threshold) was undeclared — added; (3) the OCC rung could mask the required-field rung on its three endpoints — rung 10 now explicitly defers an *omitted* `expected_*_version` to rung 11. Ladder audit rung-by-rung: no rung is masked by a stronger predicate above it. Two placements are load-bearing and deliberate: `POST /lab-orders/{id}/interpret` and both segregation-of-duties endpoints sit *outside* the gated family, which is the only reason rungs 18 and 7 are reachable at all (a frozen patient would otherwise swallow them). `ERR_LOT_EXPIRED`/`ERR_INSUFFICIENT_STOCK` (explicit lot) and `ERR_NO_ELIGIBLE_LOT` (FEFO) are disjoint by request shape. Also added `convert-to-evisit` to rung 9's `applies_to` so the messaging-included suppression has a declared error.
- **E (worked examples)**: every numeric literal recomputed in Python — intake 87/75, 60/55, 92/85; pricing 4496×3=13488 (vs 13487 the other rounding order) and the 4200 cost floor → 8400; settlement 22500/27000 at the 45/46-minute ceiling boundary and 9000 vs 27000 entitlement-vs-cash; proration 11277/19777 → net 8500 with grants 5/3 and counters 6=1+5+0; titration 500→625→313 with anchors 2026-06-03T10:00 vs 2026-06-17T10:00 (not 2026-06-19T09:00); wash-out clearance 2026-05-15; cycle_end 2026-05-30/2026-06-29; pause-extended 2026-06-09; intake expiry 2026-10-28.
- **Lint**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (732 calls scanned). Grounds-reference resolver: 0 failures across 77 instances; all names unique; all 10 stub citations resolve to real §1.8 instance names. Forbidden concurrency vocabulary: 0 hits in all three files.
- **Hard constraint honored**: no sibling task directory was listed, read, or searched.

**Orchestrator independent verification:** all 3 YAMLs `yaml.safe_load` OK; endpoints=68, entities=15, error_catalog=34, constants=48 (55 incl. nested names); independent ALL_CAPS constant-shaped-token sweep found **0 undeclared**.

## Step 3: Copy INSTRUCTION.md — 2026-08-03T18:35:15.381Z

`cp ./INSTRUCTION.md tasks/task_0921_naturopathic_functional_medicine/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-03T18:50:00.000Z

PRD generated at `workspace/PRD.md`.

## Size
513 lines, 15,222 words. Authored in 9 bounded Write/Edit calls (no oversized single write); §4/§5 tables machine-generated from the scaffold to avoid transcription drift.

## Section outline
```
1. Introduction
2. Global Specifications & System-Wide Principles
   2.1  User and Role-Based Access Control
   2.2  API Response Structure            (verbatim — byte-for-byte match verified)
   2.3  Pagination
   2.4  Resource Identity, Timestamps and the Logical Clock
   2.5  The Global Clinical Write Gate
   2.6  The Order of Refusal              (all 28 rungs, numbered, with error id + status)
   2.7  Interval Geometry: What Touching Means, Case by Case
   2.8  Money, Rounding and the Patient Cash Ledger
   2.9  Conservation Invariants           (all 4)
   2.10 Optimistic Concurrency on Parent Records  (all 3)
   2.11 Cascade Discipline
3. Business Logic & Workflows
   3.1 Building the Chart: Practitioners, Patients, Intake and Scope of Practice
   3.2 Membership Cycles, Entitlement Pools and Tier Changes
   3.3 Booking, Settling and Unwinding a Visit
   3.4 Functional Panels: Ordering, Wash-out Adjudication and Collection
   3.5 Two Ranges on One Number: Results, Red Flags and Referral Loop Closure
   3.6 Authoring a Protocol and the Three Ways It Can End
   3.7 Titration Decisions and Adverse Reactions
   3.8 The Dispensary: Lots, First-Expiry-First-Out, Pricing and Reversal
   3.9 Asynchronous Care: Message Threads, E-visits and the Superbill Loop
4. Endpoint Definitions   (68 rows, 4 columns)
5. Error Code Catalogue   (34 rows, 2 columns)
```

## Self-check results

```
Field coverage check (Contract 1):
- entities[].fields:        168 required, 168 present, 0 missing
- endpoints[].input:         98 required,  98 present, 0 missing
- endpoint output-doc keys:   7 required,   7 present, 0 missing
Status: PASS

Constant coverage: 48/48 declared constants have their value in prose, 0 missing
Error-code coverage: 34/34 appear with a trigger condition in §2/§3 AND an HTTP status
  (the seven 404 codes take their status from the collective "All of these carry HTTP 404"
   statements at ladder rungs 3 and 4, plus the §5 table)
State enumeration values: 48/48 present. Enum member values (incl. request_enums): 112/112 present.

Rule coverage check (Contract 2):
- validations[] with priority: 28 checked, 28 expressed as a numbered ladder, 0 missing
- concurrency_rules[] OCC:      3 checked, 3 expressed, 0 missing
- state_machines[].transitions: 75 checked (13 axes), 75 expressed, 0 missing
- calculations[]:               9 checked, 9 expressed incl. all 6 variant selection conditions, 0 missing
- conservation invariants:      4 checked, 4 stated as identities, 0 missing
- cascades:                     depth-5 freeze, depth-5 unfreeze, 4-link stop, 3-link supersede — all expressed
Status: PASS

Path purity check (§3 only, Contract 3): 369 backtick tokens scanned; 0 paths, 0 bare methods. PASS
```

Interval geometries stated site-by-site in §2.7 and re-stated at each point of use: half-open encounter occupancy vs **closed** membership cycles; closed lower bound on wash-out; closed 19–22 cycle-day window; and the deliberately opposite pair on one analyte — `standard_high` inclusive (`IN_RANGE`) vs `optimal_high` exclusive (already `ABOVE_OPTIMAL`). §2.5 renders both the 8-endpoint gated list and the full not-gated list.

## Places the doc-generator judged the scaffold under-specified (rendered as written, nothing invented)

1. **`Superbill.excluded_supplement_cents`** — defined via supplements dispensed "under the encounter's protocol", but `Encounter` carries no `protocol_id` and no Encounter→Protocol relation is declared. Join path not derivable; scaffold wording reproduced verbatim.
2. **`Referral.due_by_date` for `ROUTINE`** — field description scopes `RED_FLAG_REFERRAL_DUE_DAYS` to `RED_FLAG_AUTO` only, but the `POST /referrals` side effect applies 3 days to routine referrals too. Followed the endpoint side effect.
3. **`Practitioner.is_active`** — "disables for new bookings" but no rung/precondition/error enforces it. Stated without inventing a rejection.
4. **`Practitioner.credential` vs role names** — four credentials have no declared relationship to the seven RBAC roles. Left unlinked.
5. **`Protocol.symptom_score_baseline` range** — bounded to 0..`SYMPTOM_SCALE_MAX` (40) by the field description, but no rung names that bound.
6. **`professional_sample` and the cash ledger** — a `PRACTITIONER_COST` sample still increases `cash_charged_total_cents`; odd for a non-sale but unambiguous in the scaffold, rendered unconditionally.

*(Orchestrator note: none of these is the pipeline-blocking "named-but-valueless constant" pattern — all 48 constants carry values. These are scope/routing judgement calls, left for Step 9 to pin.)*

## Step 5: Generate unit tests — 2026-08-03T19:15:00.000Z

Test infrastructure and suite generated.

**`test_helpers/`** (9 modules) — `types.py` (15 entity TypedDicts + 28 enums; `LabResult` correctly omits `updated_at`/`version`), `api_client.py` (68 endpoint methods, one per PRD row), `api_errors.py` (34 codes + status map), `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py` (4 tiers of composite setup), `__init__.py`.

**`test_suite/`** — `conftest.py` + 10 domain-named files, **91 tests**.

- **(a)** `python3 -m py_compile` clean over all 20 generated `.py` files; `pytest --collect-only` collects 91/91; `pyflakes` clean.
- **(b)** `def test_` = 91, `Design:` tag lines = 91 — exact 1:1, no untagged and no dual-tagged test.
- **(c)** All 91 tags resolve to real instance `name:` values. Coverage: **24/24 difficulty instances with ≥2 tests each (48 tests)**; **43/43 non-stub corner instances with ≥1 test each (43 tests)**. All 10 `excluded_because:` stubs verified to cross-reference a real difficulty instance and were **not** translated.
- **(d)** Zero occurrences of `pytest.mark.skip` / `xfail` / `skipif`.
- **(e)** **Zero design instances skipped** — every non-stub instance passed the PRD-first two-condition filter. Two individual *assertions* were dropped inside otherwise-kept instances: the `medication_classes == []` default (PRD names the field but never its server-side default → `default-value`), and the "interaction_flags entry names the MODERATE product" claim, relaxed to an entry **count** of 1 (PRD pins "one entry per offending line" but never the entry's shape → `computed-field`).

All **174 PRD citations** machine-checked verbatim against a whitespace-normalized `PRD.md` — 0 failures.

Key notes: `parse_instant()`/`assert_same_instant()`/`assert_instant_plus_days()` route every instant comparison (zero raw string equalities on timestamps); date-only fields use `assert_calendar_date()`. Write-gate ordering hazard audited — `setup_frozen_by_scope_review()` and `setup_frozen_by_critical_result()` both build the full ACTIVE protocol / collected panel FIRST and freeze LAST. All four interval geometries exercised at their own sites (4.50 == `standard_high` → `IN_RANGE`; 2.50 == `optimal_high` → `ABOVE_OPTIMAL`, same order). Distinct owners always get distinct `X-User-ID`s. No seeded state.

## Step 6: Generate implementation — 2026-08-03T19:20:00.000Z

`workspace/implementation/` — Python + Flask, ~4,800 lines across 29 files, written incrementally.

**Layout:** `app.py` (blueprints + error handlers), `ladder.py` (ordered refusal engine), `config.py` (48 constants + catalogues), `clock.py`, `store.py`, `errors.py`, `envelope.py`, `routes/` (12 modules), `services/` (8 modules: gate, intake, labs, protocols, dispensary, threads, money, serializers).

- **(a) Endpoint completeness gate** — parsed `endpoints[]`, booted in-process, dumped `app.url_map`, diffed structurally: **scaffold 68 / registered 68 / MISSING 0 / EXTRA 0**.
- **(b) Boot** — `bash start.sh` answers HTTP in ~2s on `$PORT`, binds `0.0.0.0`, `exec`s in foreground. Kill-and-relaunch wipes all state.
- **(c) Persistence grep** — empty. In-memory dicts only; no seeding.
- Behavioural smoke suites (4 suites, ~175 assertions) all green.

**Timestamp rule.** Caller-supplied instants echoed **verbatim**. Every instant derived from the logical clock — `created_at`/`updated_at`, all `*_at` stamps, computed ones (`expires_at`, `sla_due_at`, `next_review_due_at`) — rendered in the **fractional-digit style of the string that last set the clock**. Clock starts `2026-05-01T00:00:00Z`, so an untouched clock stamps `...T00:00:00Z`, never `.000Z`. Single exception: `meta.api_request_timestamp`, pinned by §2.2 at three fractional digits.

**Enum routing policy.** One shared helper at rung 12: *every* enum-membership violation on a body field → `ERR_INVALID_ENUM` (422). `ERR_VALIDATION` (400) reserved for missing/null/wrong-type/out-of-range. Rung 11 precedes rung 12, so missing-field + bad-enum → `ERR_VALIDATION`. No per-field exceptions. **Query-string filters are not validated** — off-enum `?status=BOGUS` matches no rows.

**PRD-silent decisions (input to Step 9):**
1. Version increments — §2.4 applied to the *primary addressed* row; §2.11 read as scoped to *cascade* rows (which get `updated_at` only unless named). `POST /lab-orders/{id}/results` touches only the LabOrder; encounter complete/cancel/no-show bump the encounter.
2. Patient ownership breadth — applied on every endpoint whose role list includes `Patient` wherever the addressed resource has a determinable patient owner; skipped where there is none (`GET /practitioners/{id}`).
3. Patient-restricted superbill action — a `Patient` sending a valid action other than `REPORT_DENIAL` → `ERR_ROLE_NOT_PERMITTED` at rung 2; missing/invalid action falls through to rungs 11/12 so those stay reachable.
4. Issuing a protocol with zero lines → `ERR_INVALID_STATE` at rung 8.
5. `REISSUE` past `SUPERBILL_MAX_REVISIONS` → `ERR_INVALID_STATE` at rung 8.
6. No state check on `POST /protocols/{id}/items` nor on `PATCH /memberships/{id}/tier`.
7. `sku` / `lot_code` uniqueness not enforced (property with no error code).
8. `symptom_score_baseline` / `current_symptom_score` constrained to 0..40 → `ERR_VALIDATION`.
9. OCC type strictness — non-`int` `expected_*_version` treated as a mismatch → `ERR_STALE_VERSION`.
10. Multiple ACTIVE memberships — earliest-created ACTIVE used for pricing/messaging; entitlement lookups scan for one with sufficient units.
11. `open_red_flag_referral_id` = earliest-created RED_FLAG_AUTO referral in `{SENT, DECLINED, ABANDONED}`.
12. Auto-raised referrals carry `recipient_name`/`specialty`/`reason` = null.
13. Cascade-driven reversals record `reversal_reason`/`reversal_authorized_by_user_id` as null; only direct reverse records them.
14. `interaction_flags` entry shape: `{protocol_item_id, product_id, interaction_severity, medication_classes}`.
15. `excluded_supplement_cents` = sum of the patient's DISPENSED dispense value (Encounter carries no protocol FK).
16. Minted e-visit encounters get `scheduled_start`/`scheduled_end` = null, `base_fee_cents` = 9500, `extended_block_count` = 0.
17. Consecutive clinical replies to an `ANSWERED` thread allowed (status stays `ANSWERED`, counters accumulate).
18. `RE_REFER` without `recipient_name` keeps the previous recipient.
19. Intake expiry also materialised immediately before the rung-14 intake gates on booking and protocol issue.
20. Protocol-level discontinue reverses fills against the lines it just stopped; the line-level stop cascade reverses against all of the protocol's lines.

**Orchestrator independent verification of Steps 5+6:** `def test_` = 91 == `Design:` tags = 91; 0 skip/xfail/skipif; impl persistence grep empty; impl contains no reference to `test_suite`/`test_helpers`/`conftest`; independent `app.url_map` vs scaffold diff = 68 scaffold / 68 registered / MISSING 0 / EXTRA 0.

**Isolation note:** Steps 5 and 6 were launched concurrently in one message (correct). Step 5 finished first (~1400 s) while Step 6 ran to ~1681 s, so `test_suite/` existed on disk during Step 6's final stretch — the mirror of the task_0914 breach. Step 6 was explicitly instructed not to look for or read test files, and an independent grep of the impl tree finds no reference to the test tree. Step 7 is briefed on this to audit any *passing* test that looks impl-tuned.

## Step 7: Run tests and iterate — 2026-08-03T19:32:00.000Z

The task exited clean on the first sweep.

**Iterations run: 1.** The first 8-round sweep was clean; no fixes were needed, so no re-run was required.

**Final per-round pass counts:** 91/91 in all 8 rounds (0 failed, 0 errors, 0 skipped; ~100 s per round, run as 4 waves of 2 as staged). Verified genuine: `round.1.log` shows all 91 tests individually PASSED under per-test-server isolation.

**Tests deleted:** none. No test reached the diagnostic protocol via failure, and the isolation spot-audit found no passing test that fails STEP 1.

**Fixes applied to `test_helpers/`:** none.
**Fixes applied to `test_suite/`:** none.
**Fixes applied to `implementation/`:** none.

### Isolation spot-audit (Steps 5/6 overlap)

Audited the passing tests against the impl's own list of 20 PRD-silent decisions, covering every category named in the briefing. Verdict: **no breach — zero deletions warranted.**

Category sweeps (whole-suite greps, not samples):
- **Timestamp rendering style** — zero raw string equalities on any `*_at` field anywhere. Every instant routes through `parse_instant`/`assert_same_instant`/`assert_instant_plus_days`, which normalise fractional digits and `Z`-vs-offset. Closes the recurring `.000Z` impl-tuning bug by construction. FAIR.
- **List ordering / tie-breaks** — zero ordering assertions. Every `rows[0]` deref sits on a single-row result (`total_count == 1`); the one multi-row case (`test_01_chart_and_intake.py:170`) is a deliberately order-agnostic set-membership check. FAIR.
- **Version-bump granularity** — only 5 version assertions suite-wide, all on the primary addressed row. Nothing asserts a version on a *cascade* row, which is precisely impl silent-decision #1. FAIR.
- **Response-field projections** — `assert_*` helpers do presence/type checks on PRD-enumerated attributes, never exact key-set equality. FAIR.
- **Cascade legs that do not fire** — adverse-reaction and supersede cascade tests assert only PRD-verbatim links and never touch `reversal_reason`/`reversal_authorized_by_user_id` on the cascade path (impl decision #13, PRD-silent). FAIR.
- **Impl decisions #3, #4, #5, #9, #16** — not asserted by any test. FAIR.

Individually STEP-1'd against verbatim PRD sentences (all KEEP):

| Test | Asserted detail | PRD anchor |
|---|---|---|
| `test_01` registration defaults + `version == 1` | 10 server-owned fields | §3.1 L224 enumerates all ten; §2.4 L92 for `version` |
| `test_01` gate projection, incl. `open_red_flag_referral_id is None` | 6-field computed read | §2.5 L226 enumerates exactly those six |
| `test_06` `version_no == 2` | revision-chain numbering | §3.6 L330 "one more than the named predecessor's `version_no`" |
| `test_06` supersede: `next_review_due_at is None`, `titration_locked is False`, `SUPERSEDED_BY_REVISION` | 3-link cascade | §3.6 L336 states all three verbatim |
| `test_06` `len(interaction_flags) == 1` | MODERATE flag count | §3.6 "one entry per offending line" (entry *shape* already relaxed away at Step 5) |
| `test_03` `paused_at is None` on resume | field clearing | §3.2 L248 "`paused_at` is cleared to null" |
| `test_05` `decline_reason is None` on `RE_REFER` | field clearing | §3.5 L326 "and `decline_reason` is cleared" |
| `test_09` e-visit mint | modality/both axes/9500/`source_thread_id` | §3.9 verbatim; impl's extra nulls not asserted |
| `assertions.py` LabResult lacks `updated_at`/`version` | negative assertion | §2.4 L92 "neither may be invented for it" |
| `assert_superbill` `excluded_supplement_cents` | **presence only, value never asserted** | §3.9 names the field; the join is non-derivable (Step 4 note 1) — the generator correctly stopped at presence |

Most notable finding: the field the doc-generator flagged as having a non-derivable join path (`Encounter` carries no `protocol_id`) is the one field the suite deliberately checks for presence but never for value — evidence the test artifact was written PRD-first rather than tuned to the implementation.

**Cardinal-rule hygiene (independently re-verified):** 91 tests collected; 0 `skip`/`xfail`/`skipif`; impl contains no reference to `test_suite`/`test_helpers`/`conftest`; no SQLite/file/JSON persistence and no seeding; storage is in-memory dicts only.

**Orchestrator independent verification of the clean sweep:** re-parsed all 8 `results.N.json` — each has **91 individual rows** (not just an aggregate counter), status distribution `{'passed': 91}` in every round, and sorted test-name lists **byte-identical to round 1 in all 8 comparisons**. Summary fields read 91/91 in all 8.

## Step 8: Finalize PRD — SKIPPED

Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes and 0 `implementation/` fixes. Per the skip condition, `PRD.md` already determined every behavior the implementation exhibits at the sites Step 7 could observe, so no `PRD_FINALIZED.md` is produced. Step 9 runs against `PRD.md` directly.

## Step 9: Complete PRD — 2026-08-03T19:50:00.000Z

**File**: `workspace/PRD_COMPLETED.md`

- **PRD.md**: 513 lines / 108,207 chars → **PRD_COMPLETED.md**: 517 lines / 126,187 chars (**+17,861 chars**, +4 lines, 47 lines revised in place)
- **Ambiguity-pins: 38** · **Mismatch-revisions: 9**
- Verified empirically by booting the server on port 18921 and probing wire-level behaviour (timestamps, JSON numbers, pagination/filter edges, ladder ordering, cascade side effects), then shut down. No implementation file was modified.

### Mismatches (PRD described different behaviour)
- `§2.4` — revise — **timestamp rendering** — "exactly three fractional-second digits" was flatly wrong: caller-supplied instants echo **verbatim**, clock-derived instants inherit the fractional style of the string that last *set* the clock (untouched clock → `2026-05-01T00:00:00Z`, no fractional part), only `meta.api_request_timestamp` is fixed at 3 — `clock.py:1-18,120-145`
- `§2.6 rung 9` — revise — rung guards **four** endpoints, not five; encounter completion has no dependent-state check; membership pause is rung-8 `ERR_INVALID_STATE`; wash-out release is rung 20 — `routes/encounters.py:243-255`, `routes/memberships.py:123-142`
- `§2.1` — revise — patient-ownership is *not* enforced on every Patient-listing endpoint: `GET /practitioners/{id}` has no patient owner and is a no-op — `routes/practitioners.py:45-53`
- `§3.1` — revise — practitioner `is_active` is advisory; **no endpoint consults it**, an inactive practitioner is still bookable — `routes/encounters.py:38-153`
- `§3.6` — revise — protocol-item addition carries **no state precondition** — `routes/protocols.py:123-162`
- `§3.8` — revise — product `sku` uniqueness **not enforced** — `routes/dispensary.py:34-69`
- `§3.8` — revise — lot `lot_code` uniqueness **not enforced** — `routes/dispensary.py:91-122`
- `§3.9` — revise — `excluded_supplement_cents` is **not** scoped to the encounter's protocol (no protocol FK): sum over *all* the patient's `DISPENSED` dispenses — `routes/superbills.py:24-35`
- `§3.7` — revise — a `MILD`/`MODERATE` adverse report writes **nothing at all** (no row persisted, no `updated_at`, no `version`) — `routes/protocol_items.py:141-150`

### Ambiguity pins (38)
- `§2.11` — the **positive version rule**: addressed row (+ any narrative-named row) bumps; every cascade/side-effect row gets `updated_at` only; created rows start at 1; two writes decline even their own row — `store.py:76-85`
- `§2.11` — cascade-driven reversals leave `reversal_reason`/`reversal_authorized_by_user_id` null and don't bump — `services/dispensary.py:135-153`
- `§2.2` — every declared field always present, unset → explicit `null`; unknown path *or method* → 404 `ERR_RESOURCE_NOT_FOUND` (never 405); non-object body → empty object — `app.py:56-76`, `ladder.py:212-217`
- `§2.3` — pagination: bare-decimal-integer strings only; out-of-range offset → empty page, `total_count` intact, 200 — `ladder.py:169-195`
- `§2.3` — list tie-break is **mint order**, `id` never participates — `store.py:87-89`
- `§2.3` — filters are raw case-sensitive strings, never enum-validated (off-enum → empty page, not 422); unknown params ignored; `is_quarantined` reads true/1/yes — `ladder.py:76-90`
- `§2.4` — clock echoes `to_iso8601` verbatim incl. offset — `routes/system.py:12-24`
- `§2.4` — lazy materialisation also runs at both intake gates and before attestation state-check, never bumps `version`; `sla_breached` uses strict `>` — `services/intake.py:55-61`, `services/threads.py:8-16`
- `§2.5` — gate can't fire when the body FK naming the patient is absent → falls through to payload shape — `ladder.py:252-257`
- `§2.6 rung 2` — Patient + non-`REPORT_DENIAL` action → 403 **before path existence** — `routes/superbills.py:123-129`
- `§2.6 rung 10` — OCC strict by type; unresolvable parent also → `ERR_STALE_VERSION` — `ladder.py:271-284`
- `§2.6 rung 11` — symptom figures bounded 0..40 → `ERR_VALIDATION`; `""` is never a valid string — `ladder.py:96-98`
- `§2.7` — 14-day cascade reversal window inclusive at its far end — `services/dispensary.py:155-160`
- `§3.1` — `open_red_flag_referral_id` = earliest-created `RED_FLAG_AUTO` in {SENT, DECLINED, ABANDONED}; gate view is 6 fields only — `services/gate.py:6-21`
- `§3.1` — re-submission bumps the section; patient version untouched on submission — `routes/patients.py:211-245`
- `§3.2` — `dispensary_discount_pct` is a JSON number (`0.05`/`0.1`/`0.2`) — `services/serializers.py:93`
- `§3.2` — tier change has **no state precondition** (PAUSED/EXPIRED re-prorate) — `routes/memberships.py:236-248`
- `§3.2` — `remaining_days` not capped above — `routes/memberships.py:188-189`
- `§3.3` — minted-encounter field defaults; `scheduled_*` echoed verbatim; multi-ACTIVE membership → earliest with a unit, same one credited on cancel — `routes/encounters.py:96-125,277-291`
- `§3.4` — credit-funding membership = earliest ACTIVE with enough credits, remembered for cancellation, version never moves — `routes/lab_orders.py:96-101,409-414`
- `§3.5` — result posting moves status without moving `version`; response is the `LabResult` — `routes/lab_orders.py:244-249`
- `§3.5` — auto-raised referral: `recipient_name`/`specialty`/`reason` null, `attempt_no` 1 — `routes/lab_orders.py:279-297`
- `§3.5` — escalation fires at most once; `CRITICAL_ESCALATED` refuses further results — `routes/lab_orders.py:211-213`
- `§3.5` — every referral action recomputes the gate; patient touched only on an actual change — `routes/referrals.py:151-156`
- `§3.5` — `RE_REFER` without `recipient_name` keeps the previous; ABANDONED branch preserves recipient and decline reason — `routes/referrals.py:140-148`
- `§3.6` — `symptom_score_baseline` out of 0..40 → `ERR_VALIDATION` — `routes/protocols.py:60-65`
- `§3.6` — zero-line issue → `ERR_INVALID_STATE` at rung 8, before the intake gate — `routes/protocols.py:167-174`
- `§3.6` — `interaction_flags` entry shape (4 keys, sorted classes); overwritten wholesale on issue — `routes/protocols.py:199-206`
- `§3.6` — med-class matching is free-form, exact, case-sensitive — `routes/protocols.py:187-193`
- `§3.6` — protocol-level discontinue reverses only against the lines *it* stopped — `routes/protocols.py:295-301`
- `§3.6` — computed `last_dose_date` on every line read — `services/serializers.py:189-191`
- `§3.7` — `current_symptom_score` bounded 0..40 → `ERR_VALIDATION` — `routes/protocol_items.py:119-126`
- `§3.7` — line-level cascade reverses against **all** the protocol's lines; three total-no-op branches; protocol's version not bumped — `services/protocols.py:51-62`
- `§3.7` — SEVERE bumps the line's version; own-state check runs only for SEVERE and precedes payload validation — `routes/protocol_items.py:135-148`
- `§3.8` — multi-ACTIVE pricing uses the earliest-created membership regardless of balances — `services/dispensary.py:25-28,114-129`
- `§3.9` — no message row is ever persisted; threads carry counters, not transcripts — `routes/threads.py:21-62`
- `§3.9` — `clinical_minutes` optional/defaults 0/ignored on patient posts; consecutive clinical replies self-loop on ANSWERED — `routes/threads.py:117-131`
- `§3.9` — minted e-visit field set (`scheduled_*` null, base fee 9500, blocks 0, no service code); thread version not bumped by conversion — `routes/threads.py:176-201`
- `§3.9` — superbill draft does not cross-check `patient_id` against the encounter, imposes no encounter state — `routes/superbills.py:51-87`
- `§3.9` — superbill ISSUE/VOID encounter-axis negative branches — `routes/superbills.py:164-182`
- `§3.9` — `REISSUE` past 3 revisions → `ERR_INVALID_STATE`; action narrative fields all optional — `routes/superbills.py:131-139`

### Scanned and found genuinely CLEAN (already uniquely pinned)
The eight-endpoint clinical-write-gate set and its rung-6 position; all 28 ladder rungs' relative order and error codes; the 34-code error/HTTP catalogue; every state machine's declared source states; the four interval geometries and both opposite analyte bounds; dual-variant intake scoring and both thresholds; membership tier constants and the ten-step proration sequence; roll-cycle forfeiture both ways; all four conservation identities; entitlement-covers-base-fee-only settlement split; extended-block ceiling and 24-hour inclusive refund window; telehealth 10-minute turnaround buffer and EVISIT invisibility to occupancy; the four panel catalogue blocks; wash-out clearance derivation and closed lower bound; FEFO ordering and tie-break; per-unit-before-multiplication rounding with the acquisition-cost floor; the titration ladder's four bands, dose multipliers and both anchoring formulas; `discontinue_reason` routing across all three stop routes; the three OCC endpoints; the 201-vs-200 split; and the full role tables in §4.

**Orchestrator final verification:** `PRD_COMPLETED.md` present (517 lines); no implementation file modified after `results.8.json` (the 91/91 × 8 result stands for the shipped code); no stray server left on port 18921; 0 scaffold references leaked into `PRD_COMPLETED.md`.

## PIPELINE COMPLETE — 91/91 × 8 rounds, 0 fixes.
