## Step 1: Create task directory — 2026-09-04T06:27:00.000Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2686_telephone_number_administration_pooling and its workspace/ subdirectory (pre-assigned path from orchestration prompt; no index scan performed).

## Step 2: Generate scaffold — 2026-09-04T08:24:00.000Z

Scaffold generation for task 2686 is complete and lints clean.

## Files

| File | Lines | Top-level key |
|---|---|---|
| `SCAFFOLD.yaml` | 2960 | §1.0–§1.7 only (no `scaffold_difficulty_design`, no `scaffold_corner_design`) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1979 | `scaffold_difficulty_design` |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4413 | `scaffold_corner_design` |

All three parse with `yaml.safe_load`.

## Scaffold counts (§1.0–§1.7)
`api_prefix: /numbering`, `domain_name: telephone-number-administration-pooling`; complexity profile: primary `quota_allocation`, secondary `compliance_audit`, layers `optimistic_concurrency / cascading_side_effects / dual_variant_calculation / rate_threshold_triggers`, topology `graph`, machine shape `cyclic`, role model `segregation_of_duties`, consistency `immediate`.

- 12 entities, 11 state machines, 2 concurrency rules, 10 calculations
- 34 ordered validations (priority 1–34), 50 endpoints, 43 errors, 5 roles

## Design instance counts
- §1.8: 9 rule_ids × 2+ instances = **20 instances** (2 per rule, one rule carrying 3 boundary instances)
- §1.9: **117 instances** across the 9 mandated sections — entities 14, state_machines 22, calculations 15, validations 14, endpoints 6, errors 24, rbac 9, cross-cutting complexity layers 10, consistency model 3. Of these, 97 are active `test_recipe` instances and 20 are `excluded_because:` stubs, each citing a §1.8 instance that exists by name (verified programmatically); all 137 names across both files are unique.

## Lint verdict (verbatim)
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
Coverage
  §1.5 endpoints declared:    50
  §1.1 entities declared:     12
  §1.8 instances scanned:     20
  §1.9 instances scanned:     97
  Calls scanned (§1.8+§1.9):  1157

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Notable fixes made while finishing
- Three sub-resource GET paths had to use the spec's literal `{id}` placeholder to satisfy lint check (f): `GET /numbering/utilization-filings/{id}/audit-findings`, `GET /numbering/relief-plans/{id}/comments`, `GET /numbering/blocks/{id}/routing-records` (POST siblings keep their descriptive placeholders; the PublicCommenter role allow-list was updated to match).
- Earlier in the run, several unreachable-error and non-total-state-machine contradictions in SCAFFOLD.yaml were repaired so every error code is triggerable: split `ERR_BLOCK_NOT_POOLING_ELIGIBLE` (priority 28, contamination-blocked pool) from `ERR_POOL_INSUFFICIENT_BLOCKS` (priority 33, empty pool); removed licence expiry and probation from the computed `Carrier.eligibility_status` so priorities 14/15 can fire; made `probation_until` time-aware (which is what makes the new `rate_threshold_triggers` "reset works" instance possible); added the `ACTIVE <-> EXHAUSTED` NPA edges to make the machine total w.r.t. `npa_exhaust_posture`; made the comment window half-open `[open, close)`.
- No sibling task directory was read, listed, or grepped at any point.

## Step 3: Copy shared files — 2026-09-04T08:25:00.000Z

Copied ./INSTRUCTION.md to tasks/task_2686_telephone_number_administration_pooling/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T08:47:00.000Z

PRD generation is complete and verified.

## Output
`workspace/PRD.md` — **494 lines**, written in 12 sequential chunks (1 `Write` + 11 `cat >>` heredocs), never in one call.

## Section list
- 1. Introduction
- 2. Global Specifications & System-Wide Principles — 2.1 RBAC · 2.2 API Response Structure (verbatim) · 2.3 Pagination · 2.4 Record Identity, Timestamps and Revision Counters · 2.5 The Logical Clock · 2.6 Utilization Arithmetic, Precision and Rounding · 2.7 Optimistic Concurrency Control · 2.8 Nested Resource Retrieval and Path Resolution · 2.9 Cascade Discipline and Counter Recomputation · 2.10 The Recorded Actor Trail · 2.11 Order of Precedence Among Validations (11 subsections)
- 3. Business Logic & Workflows — 3.1 Qualifying a Carrier · 3.2 Stocking the Inventory (+ Area Code Exhaust Posture) · 3.3 Utilization Reporting and the Audit Programme · 3.4 Filing for Numbering Resources · 3.5 Review, Entitlement and the Pool Draw (+ The Entitlement Calculation, Drawing Blocks From the Pool) · 3.6 Thousand-Block Pooling and Donation Obligations · 3.7 Activation, Reclamation and Aging (+ The Reclamation Sweep, Working an Order Through to Execution) · 3.8 Routing Data, Portability and Number Ports (+ Porting a Single Number) · 3.9 Area Code Relief Planning (+ Public Comment and the Weighted Tally, Ordering Relief) (9 subsections)
- 4. Endpoint Definitions — 50-row table, exactly 4 columns
- 5. Error Code Catalogue — 43-row table, exactly 2 columns

**Ending confirmed:** last line is the `ERR_GRANT_EXCEEDS_ENTITLEMENT | 422` table row, i.e. the completed §5 table. No mid-sentence truncation. (Orchestrator independently verified tail + section list.)

## Hard Contract reports
- **Contract 1 — Field-Name Coverage: PASS (153/153).** 146 appear as inline code; the remaining 7 (`block_id`, `filing_id`, `finding_id`, `order_id`, `plan_id`, `port_request_id`, `request_id`) are path parameters appearing as `{…}` segments in the §4 path column.
- **Contract 2 — Rule Coverage: PASS.** All 43 error ids referenced in §2/§3 prose; all 34 validations enumerated in §2.11; all 10 calculations rendered in prose; both concurrency rules in §2.7; all 79 state-machine edges across 11 machines have both state names and driving action keyword in prose.
- **Contract 3 — §3 Path Purity: PASS (0 violations over 319 backticked tokens in §3).**

Additional checks: §2.2 byte-identical to the shared response-structure template; zero SCREAMING_CASE constants leaked; zero fuzzy words; zero pseudocode operators outside the §2.2 JSON. Neither design yaml was opened, grepped or referenced; no sibling task read.

## Scaffold issues found and how each was resolved in the prose
1. **Gap — `PERMISSIVE_DIALING_DAYS` has no numeric value anywhere in the scaffold.** Fixed at **180 days**, stated concretely in §2.5 and §3.9.
2. **`npa_exhaust_posture` vs the `JEOPARDY → ACTIVE` edge.** Scoped the stamp clause to codes currently at `EXHAUSTED`, reconciling function with every edge.
3. **"Effective filing" status set.** Field description says SUBMITTED/ACCEPTED; validation 29 and two input_sets say SUBMITTED/ACCEPTED/REJECTED. Defined "effective filing" once as the newest of the three (§3.3); documented the sweep's narrower SUBMITTED/ACCEPTED + `strict_utilization_pct` test separately (§3.7).
4. **`RECLAMATION_REFERRAL` probation.** Adopted: stamp probation for both penalty types **and** increment `reclamation_strike_count` for the referral.
5. **Superseded routing record's `end_at`.** Adopted the endpoint's rule (incoming record's `effective_at`) over the machine's `clock_now`; the two coincide for port activation and snapback.
6. **`months_in_operation` threshold has no error id.** Rendered as descriptive request-type context rather than an enforced validation.
7. Corrected counts: 43 error codes and 10 calculations; §5 matches the scaffold error set exactly; §4 matches all 50 endpoints in method, path and order.

## Step 5: Generate unit tests — 2026-09-04T10:50:00.000Z

ORCHESTRATOR NOTE (deviation, recorded per autonomy rule): Steps 5 and 6 were NOT launched in the same assistant message as the skill requires; Step 5 ran to completion first. The lost property is physical isolation — `test_suite/` and `test_helpers/` now exist on disk when the Step 6 impl generator starts. Mitigation applied instead of re-running Step 5 (which would have cost ~2h of work for no artifact gain): Step 6's prompt carries an explicit, itemized prohibition on reading, listing, globbing or grepping `test_helpers/`, `test_suite/`, and both SCAFFOLD design yamls, plus a requirement to state in its summary that it never touched them. Orchestrator verified both test dirs are at the task root and no test_* strays exist under workspace/.

Test generation for `task_2686_telephone_number_administration_pooling` is complete and verified.

## Output

All files at the task root. Nothing was written under `workspace/` (confirmed: `workspace/` holds only `INSTRUCTION.md` and `PRD.md`), and nothing was read from or written to `workspace/implementation/`.

`test_helpers/` — 2360 lines over 9 modules: `__init__.py` 75, `api_client.py` 276, `api_errors.py` 99, `assertions.py` 291, `constants.py` 77, `factories.py` 204, `fixtures.py` 784, `test_users.py` 73, `types.py` 481.

`test_suite/` — 6639 lines, 137 tests:
| file | lines | tests |
|---|---|---|
| `conftest.py` | 25 | – |
| `test_01_utilization_arithmetic.py` | 202 | 4 |
| `test_02_exhaust_projection.py` | 209 | 4 |
| `test_03_entitlement_and_pool_draw.py` | 293 | 6 |
| `test_04_pooling_donation.py` | 99 | 2 |
| `test_05_review_cycles.py` | 309 | 6 |
| `test_06_cascades.py` | 340 | 6 |
| `test_07_routing_and_porting.py` | 439 | 10 |
| `test_08_relief_planning.py` | 192 | 4 |
| `test_09_corner_entities.py` | 502 | 13 |
| `test_10_corner_state_machines.py` | 866 | 19 |
| `test_11_corner_calculations.py` | 490 | 11 |
| `test_12_corner_validations.py` | 387 | 9 |
| `test_13_corner_endpoints.py` | 313 | 6 |
| `test_14_corner_errors_not_found.py` | 250 | 8 |
| `test_15_corner_errors_conflicts.py` | 238 | 5 |
| `test_16_corner_errors_gates.py` | 376 | 7 |
| `test_17_corner_rbac.py` | 451 | 9 |
| `test_18_corner_cross_cutting.py` | 365 | 5 |
| `test_19_corner_consistency.py` | 293 | 3 |

## Tests per queue
- Queue A (`Design: Difficulty/...`): **42 tests** over all **20** live difficulty instances (files 01–08).
- Queue B (`Design: Corner/...`): **95 tests** over **95** live corner instances (files 09–19).

## Design-index audit (machine-checked)
- 137 tagged tests, 115 distinct tags, **0 malformed**; **0 unknown tags**; **0 stub instances tagged** (20 stub-shaped instances correctly excluded).
- Live instance coverage **115/117**. Every group fully covered except `Corner/state_machines` at 19/21.
- No `xfail`, no `pytest.mark.skip`, no placeholders, no reference to the scaffold or design docs anywhere in the generated code.
- `python3 -m py_compile` clean on all 29 generated `.py` files.

## Instances skipped (2, both `Corner/state_machines`)
Both fail condition 2 of the PRD-first filter — the PRD does not uniquely derive the asserted outcome, in fact it derives a different one.

1. **`carrier_revoked_license_is_terminal_and_refuses_reinstate`** — asserts `REINSTATE` on a `REVOKED` carrier returns `ERR_TERMINAL_STATE` (409) rather than `ERR_INVALID_STATE_TRANSITION`. PRD §2.11 priority 9 enumerates the terminal states exhaustively and the carrier/licensing machine is not among them, so the terminal-state check does not attach to a carrier. The prose "`REVOKED` is terminal on the licensing axis" is descriptive; `REINSTATE` is defined only as `SUSPENDED → GRANTED`, pointing at priority 10 / `ERR_INVALID_STATE_TRANSITION`.
2. **`relief_plan_withdraw_releases_the_npa_from_relief_planned`** — asserts the area code reads `JEOPARDY` with `jeopardy_declared_at` retained after `WITHDRAW` while five `POOL_AVAILABLE` blocks remain. PRD's recomputation clauses derive `ACTIVE` with a null stamp — the opposite of the asserted outcome — so the instance is unsound as written.

## Step 6: Generate implementation — 2026-09-04T11:33:00.000Z

Implementation complete.

## What was built
`workspace/implementation/` — Python 3 + Flask, in-memory dict store only (no SQLite, no files, no /tmp cache), store completely empty on every boot, no seeded/preloaded entities anywhere. **4095 lines / 23 .py files + start.sh + requirements.txt**: `app.py` 88, `db.py` 161, `errors.py` 64, `middleware.py` 210, `response.py` 84, `routes/common.py` 34, `routes/clock.py` 18, `routes/carriers.py` 214, `routes/npas.py` 107, `routes/rate_centers.py` 144, `routes/blocks.py` 208, `routes/allocation_requests.py` 350, `routes/filings.py` 303, `routes/reclamation.py` 183, `routes/relief.py` 363, `routes/ports.py` 254, `services/constants.py` 143, `services/calc.py` 278, `services/core.py` 393, `services/serialize.py` 271, `services/workflows.py` 214.

`start.sh` sets `-euo pipefail`, `cd`s to its own directory, pip-installs only when `import flask` fails (so per-test reboots do not contend), and `exec python3 app.py`; the app listens on `PORT` (default 10000) and boots a fresh, empty store every time.

## Endpoint coverage
**50 / 50** routes from the PRD §4 table are registered — verified by enumerating `app.url_map` (1 clock + 49 `/numbering/...`), path-for-path.

## Verification performed
- `python3 -m py_compile` clean on all 23 `.py` files.
- Smoke tests against live servers on high ports (15731–15736), each killed by the exact PID resolved from `ss -ltnp` for that port — no pattern kills of any kind. All ports confirmed released.
- End-to-end scenarios with zero HTTP 500s: clock set; carrier register → GRANT → ATTEST → VERIFY (ELIGIBLE); NPA + rate center + 8–10 blocks; utilization filing (claimed 51.68 / strict 50.18) → submit; audit finding OVERSTATED (adjusted 30.09, penalty RECLAMATION_REFERRAL) → SoD refusal for the auditor then ACCEPT by another approver → filing REJECTED, carrier PROBATION; pooling BEGIN → COMPLETE with donations (10 held @ 30.09 → 50% band → 5 donated, dirtiest-first); allocation request INITIAL (months 4.80) → APPROVE → 1 block RESERVED → activation-confirmation → ASSIGNED; routing publication (LERG_PUBLISHED, `npac_db_version` 1); port request → CONCUR → ACTIVATE (PORT_LOCKED, version 2) → CANCEL snapback (back to LERG_PUBLISHED, pre-port LRN restored, version 3, exactly one open PUBLISHED row); reclamation sweep (5 UTILIZATION_SHORTFALL orders) → SURRENDER → EXECUTE (AGING, strike) → second sweep releases the aged block; REVOKE cascade; relief planning overlay branch (weighted tally 2.50 vs 2.00 → ALL_SERVICES_OVERLAY, successor minted with `permissive_dialing_end_at` = effective_at + 180d) and split branch (parent RETIRED, rate centers/blocks re-homed); plan WITHDRAW reverting the NPA from RELIEF_PLANNED. Error-precedence spot checks returned the expected single error in each case.

## Notable interpretation decisions
- Full geographic split: the parent's `POOL_AVAILABLE` blocks are retired using the pre-move block set, since otherwise the PRD's "only path by which a block reaches RETIRED" would be unreachable; block versions are not bumped there because §3.9 enumerates only the plan, both NPAs and each moved rate center.
- A superseded earlier port request keeps its `SUBMITTED` status (only the new row stamps `supersedes_port_request_id`), since no `SUPERSEDED` value exists in the port machine.
- `exhaust_projection_months` stays at the 999.00 sentinel: the PRD never defines an NPA's "trailing monthly assignment rate", so that rate is always zero.
- Port creation checks the gaining carrier's eligibility (precedence 13), accepting `ELIGIBLE` and `PROBATION`.

## Prohibited paths
Never read, listed, globbed, grepped, or otherwise inspected `test_helpers/`, `test_suite/`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, or any sibling task directory. Sources were only `SKILL.md`, `workspace/INSTRUCTION.md`, `workspace/PRD.md`, `SCAFFOLD.yaml`, and self-written files.

## Step 7: Run tests and iterate — 2026-09-04T11:53:00.000Z

Clean sweep achieved.

**Iterations run:** 3 (each an 8-round parallel `setsid nohup` sweep, 137 tests/round). Final sweep: **137 passed / 0 failed in all 8 rounds.** Orchestrator independently verified all 8 `results.$i.json` files exist and each reads passed=137 failed=0 total=137 errors=0.

Failure trajectory: 93/137 → 135/137 → 137/137.

**Tests deleted:** none. Every failing test traced to a verbatim PRD sentence and survived the unique-derivability check.

**Fixes applied to `test_suite/`** (3 assertion mis-translations; STEP 2 "test is wrong"):
- `test_10_corner_state_machines.py:673` — `TestRevocationFansOutAcrossThreeEntityTypes`: asserted `blocks_held_count == 0` after a licence revocation, but §2.9 defines that counter over `RESERVED`, `ASSIGNED` **or** `RECLAMATION_PENDING`, and the same test asserts both blocks land in `RECLAMATION_PENDING` still holding `holder_carrier_id`. Corrected to `== 2`.
- `test_11_corner_calculations.py:418` — `TestADeltaOfExactlyFivePointsIsProbation`: asserted `eligibility_status == "ELIGIBLE"` but built the carrier via `_licensed_carrier_with_a_rate_center()`, which never drives the facilities axis (`NOT_SUBMITTED` → §3.1 makes it `INELIGIBLE`). Setup replaced with `create_eligible_carrier("A")` + `setup_npa_with_rate_center()` so the precondition matches the assertion; the assertion itself kept at full strength.
- `test_17_corner_rbac.py:449` — `TestTheRecommenderCannotOrderTheReliefItRecommended`: asserted the area code reads `JEOPARDY` after `OPEN_COMMENT`, but §3.9 states `OPEN_COMMENT` "sets the area code's `status` to `RELIEF_PLANNED` if it is not already" and only a plan withdrawal releases it. Corrected to `RELIEF_PLANNED`.

**Fixes applied to `test_helpers/`:** none needed.

**Fixes applied to `implementation/`:**
- `db.py` — added `fmt_instant()`, an ISO-8601 renderer at second precision (falling back to milliseconds for genuinely sub-second values). §2.4 pins the "exactly three fractional digits" rule to `created_at`/`updated_at` only (and §2.2 to `api_request_timestamp`); every other instant the PRD prints is second-precision, including the normative `"the logical clock reads exactly 2026-08-01T00:00:00Z"` and `"becomes due on 2027-01-28T00:00:00Z"`. This one bug accounted for 42 of the 44 initial failures.
- `services/serialize.py`, `routes/clock.py`, `routes/reclamation.py` — switched every domain instant (`activation_due_at`, `assigned_at`, `activated_at`, `aging_release_at`, `license_expires_on`, `probation_until`, `submitted_at`, `issued_at`, `response_due_at`, `executed_at`, `decided_at`, comment/relief windows, routing `effective_at`/`end_at`, port stamps, `current_utc`, `swept_at`, …) to `fmt_instant`, leaving `created_at`/`updated_at`/`api_request_timestamp` on the three-digit `fmt_dt`.
- `routes/reclamation.py:_execute` — `push_pending_growth_requests_to_info()` ran on every execution. §3.7 makes step four fire "because the carrier entered probation", i.e. only once step three's two-strike condition holds; moved the call inside the `reclamation_strike_count >= 2` branch so a first strike leaves the pending queue in `PENDING_REVIEW`.

No test was skipped, xfailed, or weakened; no assertion was downgraded from an `error_id` to an HTTP status; no data is seeded at startup and storage remains in-memory only.

## Step 8: Finalize PRD — 2026-09-04T11:58:00.000Z

Done. `PRD_FINALIZED.md` written with two surgical edits.

**Counts:** PRD.md 494 lines / 123,056 bytes → PRD_FINALIZED.md 494 lines / 123,910 bytes (line delta 0%, byte delta +854, +0.69%). Both edits extend existing sentences in place; no new sections, no line-count change.

**Changes**
- §2.4 — insert — pinned the instant-rendering split: three fractional digits are confined to `created_at`, `updated_at` and `api_request_timestamp`; every other published instant renders at whole-second precision (`YYYY-MM-DDTHH:MM:SSZ`), falling back to the three-digit form only for a genuinely non-zero sub-second value — `db.py:75-100` (`fmt_instant`), `services/serialize.py:21-267`, `routes/clock.py:18`, `routes/reclamation.py:52`, `response.py:27`.
- §3.7 — revise — step four of the reclamation-execution cascade now fires only when step three fired (strike counter at two), with an explicit statement that a first strike leaves the carrier's pending `GROWTH`/`POOL_REPLENISH` requests in `PENDING_REVIEW` — `routes/reclamation.py:148-158`.

**Pre-edit search log**
1. Edit 1 — (a) Subject: the serialized wire format of every datetime the API emits. (b) Enumerated/read: `db.py` `fmt_dt` (three-digit, always) and `fmt_instant` (second precision with ms fallback); `response.py:27` (`api_request_timestamp` → `fmt_dt`, real wall clock); every field in `services/serialize.py` (all 12 serializers: `created_at`/`updated_at` → `fmt_dt`; `license_expires_on`, `probation_until`, `jeopardy_declared_at`, `permissive_dialing_end_at`, `pooling_effective_at`, `assigned_at`, `activation_due_at`, `activated_at`, `aging_release_at`, `decided_at`, `submitted_at`, `issued_at`, `response_due_at`, `executed_at`, comment/relief window fields, `effective_at`, `window_end_at`, `desired_due_at`, `concurred_at`, `closed_at`, routing `effective_at`/`end_at` → `fmt_instant`); `routes/clock.py:18` (`current_utc`); `routes/reclamation.py:52` (`swept_at`); grepped all `object_response({` dict literals in `routes/` for any other raw-datetime emission (only `current_utc`). (c) Adjustment: wrote the rule as a confinement of the three-digit form to the three named fields plus an explicit sub-second fallback clause, rather than a flat "all instants are second-precision" claim, so the ms-fallback path is not mis-described; enumerated the covered field families illustratively rather than exhaustively so no off-path instant is excluded by omission.
2. Edit 2 — (a) Subject: the system-driven probation push of pending growth requests. (b) Enumerated/read: `routes/reclamation.py:131-168` (`_execute`; push inside the `>= RECLAMATION_PROBATION_STRIKES` branch, `else` merely touches the carrier); `services/core.py:374-386` (`push_pending_growth_requests_to_info`: `PENDING_REVIEW` + `GROWTH`/`POOL_REPLENISH`, `created_at` ascending, `touch` bumps version and leaves `reviewer_user_id` alone); `routes/filings.py:270-303` (audit-disposition path — pushes on *any* non-`NONE` penalty, independent of the strike counter); `services/core.py:388` (`enter_probation`, dead code, no callers); PRD §3.3 and §3.5 paragraphs describing the same edge. (c) Adjustment: scoped the new condition to "step three/step four" of the §3.7 execution cascade only, and phrased the second sentence as "an execution that leaves the strike counter short of two", so the §3.3 audit path (which pushes without any strike condition) and §3.5's generic wording remain true; deliberately avoided "exactly two" since the impl tests `>= 2`.

No PRD edits were made for the three `test_suite/` fixes (§2.9 `blocks_held_count` over `RESERVED`/`ASSIGNED`/`RECLAMATION_PENDING`, §3.1 eligibility requiring `VERIFIED` facilities, §3.9 `OPEN_COMMENT` setting `RELIEF_PLANNED`) — each verified against `services/core.py:104-112`, `services/core.py:182-198` and `routes/relief.py:237-255`; the existing PRD prose already determines the implemented behavior verbatim.

## Step 9: Complete PRD — 2026-09-04T12:31:00.000Z

ORCHESTRATOR NOTE: Step 9 was run as three sequential module-partitioned passes over one shared `PRD_COMPLETED.md` (pass 1 performed the `cp` from PRD_FINALIZED.md; passes 2 and 3 were explicitly forbidden from re-copying). Partition: pass 1 = infra + carriers/npas/rate_centers/blocks + constants; pass 2 = allocation_requests + filings + calc entitlement/utilization; pass 3 = reclamation + relief + ports + workflows + the four §3.6/§3.9 calc functions. Rationale: a single-agent full scan of 4095 impl lines against a 494-line PRD reliably under-scans and can leave the output byte-identical to its source. Orchestrator verified the result is NOT byte-identical (md5 837262c8… → 854e0e95…, 58 changed lines, +17,738 chars over PRD_FINALIZED.md).

**Totals across the three passes:** PRD_FINALIZED.md 494 lines / 123,910 chars → PRD_COMPLETED.md 494 lines / 141,648 chars (+17,738 chars, line count unchanged — every edit in-paragraph, no new sections). **70 prose changes: 47 ambiguity-pins, 23 mismatch-revisions.**

### Pass 1 (infra + carriers/inventory) — 21 ambiguity-pins, 4 mismatch-revisions
- 2.1 — revise — ambiguity — a header holding only whitespace counts as empty for `ERR_UNAUTHENTICATED` — middleware.py:30
- 2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars — response.py:21
- 2.2 — insert — ambiguity — `api_request_timestamp` is the host's real clock, not the logical clock — response.py:27
- 2.3 — insert — ambiguity — non-integer `limit`/`offset` is `ERR_INVALID_REQUEST`, empty string falls back to default, offset past the end yields an empty page with full `total_count` — response.py:55-84
- 2.3 — insert — ambiguity — every ordering breaks `created_at`/`effective_at`/`submitted_at` ties by insertion order — db.py:184-189, core.py:89, relief.py:193
- 2.3 — insert — ambiguity — filters are exact, case-sensitive, conjunctive; empty-string filter ignored; unmatched value returns an empty page — routes/common.py:23-30
- 2.5 — insert — ambiguity — clock may move backwards; instants parsed ISO 8601 and normalized to UTC, naive read as UTC, unparseable is `ERR_INVALID_REQUEST` — db.py:103-118, middleware.py:158
- 2.9 — insert — ambiguity — `version` advances at most once per row per HTTP request however many cascade steps write it — app.py:47-50, db.py:164-181
- 2.11 (item 3) — insert — ambiguity — JSON `null` counts as absent; absent/empty body reads as `{}`; non-object body is `ERR_INVALID_REQUEST`; undeclared properties ignored — middleware.py:60-76
- 3.1 — revise — mismatch — "all four of its counters" listing three → "all three" — serialize.py:26-28
- 3.1 — insert — ambiguity — `license_expires_on` required for GRANT/RENEW and ignored otherwise; `reason` ≤500 chars, not retained; every unavailable licence action is `ERR_INVALID_STATE_TRANSITION` — carriers.py:98-131
- 3.1 — insert — ambiguity — `note` ≤1000 chars, not retained; `switch_clli`/`interconnection_ready` shape-checked but ignored on VERIFY/FAIL — carriers.py:186-188
- 3.2 — revise — mismatch — `exhaust_projection_months` always publishes the 999.00 sentinel (no code-level assignment history stored) — serialize.py:46
- 3.2 — insert — ambiguity — duplicate rate-center `name` is `ERR_INVALID_REQUEST`, tested after the jurisdiction check — rate_centers.py:50-58
- 3.2 — insert — ambiguity — the per-code rate-center listing takes the same filters minus `npa_id` — npas.py:87-94
- 3.2 — insert — ambiguity — rate center whose `npa_id` disagrees with the block's is `ERR_INVALID_REQUEST` — blocks.py:48
- 3.2 — insert — ambiguity — an `INELIGIBLE`/`SUSPENDED` holder on block load is `ERR_INVALID_STATE_TRANSITION`, not `ERR_CARRIER_NOT_ELIGIBLE` — blocks.py:51-56
- 3.2 — insert — ambiguity — `mark_activated` has no effect without `holder_carrier_id` — blocks.py:82-88
- 3.2 — revise — mismatch — posture recomputation is triggered by changes to the available count (a no-op recompute still bumps `version`); the revocation cascade touches neither posture nor `version` — carriers.py:138-171, blocks.py:94, core.py:340-360
- 3.2 — insert — ambiguity — manual jeopardy `reason` optional/not retained; a non-`ACTIVE` code is `ERR_INVALID_STATE_TRANSITION` — npas.py:102-105
- 3.6 — insert — ambiguity — any pooling action against a `POOLED` rate center is `ERR_INVALID_STATE_TRANSITION`, not `ERR_TERMINAL_STATE` — rate_centers.py:123-133
- 3.7 — insert — ambiguity — activation confirmation on `RETIRED` is `ERR_TERMINAL_STATE`, other non-`RESERVED` `ERR_INVALID_STATE_TRANSITION`; `activated_number_count` is 0–1000 — blocks.py:127-137
- 3.8 — insert — ambiguity — `RETIRED` block is `ERR_TERMINAL_STATE`, other postures (incl. `PORT_LOCKED`) `ERR_INVALID_STATE_TRANSITION` — blocks.py:161-172
- 3.8 — insert — ambiguity — publication answers 201 with the routing record itself (not the block); `ocn` null when the block has no holder — blocks.py:183-199
- 3.8 — revise — mismatch — non-future re-home from `LERG_PUBLISHED` is `ERR_INVALID_STATE_TRANSITION`; one general landing rule governs every accepted publication including from `ROUTING_PENDING` — blocks.py:173-197

### Pass 2 (allocation requests + filings + calc) — 11 ambiguity-pins, 6 mismatch-revisions
- 3.3 — insert — ambiguity — a `DRAFT` filing already carries both percentages computed at creation; creation touches no other row — filings.py:81-84
- 3.3 — insert — ambiguity — neither figure is clamped to 100.00 and the five counts are never validated against `blocks_held_at_period_end` — calc.py:18-22
- 3.3 — insert — ambiguity — a `license_status` other than `GRANTED` is `ERR_INVALID_STATE_TRANSITION`, tested after the filing's own status check — filings.py:124-127
- 3.3 — insert — ambiguity — a missing `amendment_note` is `ERR_INVALID_REQUEST` evaluated last, after transition legality and both licence tests — filings.py:131-133
- 3.3 — revise — mismatch — the body's `utilization_filing_id` is shape-checked then discarded; the path filing is always stored — filings.py:156,201
- 3.3 — insert — ambiguity — the `adjusted_numbers_assigned` ceiling is an `ERR_INVALID_REQUEST` raised after path resolution but before the filing's terminal/transition checks — filings.py:177-188
- 3.3 — insert — ambiguity — an omitted `disposition_note` preserves the creation-time note rather than clearing it — filings.py:254-255
- 3.3 — revise — mismatch — the aggregate is recomputed from the filing's reported counts, never the audited figure; rate center's `version` not bumped — core.py:274-311, filings.py:282-295
- 3.4 — insert — ambiguity — `INITIAL` is intent, not a checked precondition; a carrier already holding blocks is not refused — allocation_requests.py:81-92
- 3.5 — insert — ambiguity — the three optional review fields are shape-checked on every action then discarded; neither note is retained — allocation_requests.py:174-179
- 3.5 — revise — mismatch — only `REVIEWER_DENIED` and `CARRIER_PROBATION` are ever written as `denial_reason` — allocation_requests.py:224, constants.py:82-87
- 3.5 — insert — ambiguity — `ERR_CARRIER_ON_PROBATION` also fires on `reclamation_strike_count` reaching 2, not only on a live `probation_until` — core.py:190-193, allocation_requests.py:254-255
- 3.5 — revise — mismatch — "never an approval" was false: a zero demand ceiling is not gated, so the request is approved with `granted_block_count` 0 and empty `assigned_block_ids` — calc.py:165-172,193
- 3.5 — insert — ambiguity — the gate reads the unbumped tier cap, so a `POOL_REPLENISH` below 60.00 in a `POOLED` rate center is still refused — allocation_requests.py:265, calc.py:189-190
- 3.5 — revise — mismatch — `ERR_BLOCK_NOT_POOLING_ELIGIBLE` also covers precandidates excluded by the pristine-only rule — calc.py:128-135
- 3.5 — insert — ambiguity — `granted_block_count` of 0 is legal and approves with zero blocks; negative is `ERR_INVALID_REQUEST` — allocation_requests.py:178,286-293
- 3.5 — revise — mismatch — the holding carrier's `version` also increments unconditionally, as does the area code's — allocation_requests.py:313-319

### Pass 3 (reclamation + relief + ports) — 15 ambiguity-pins, 13 mismatch-revisions
- 2.8 / 2.11 step 5 — insert+revise — mismatch — reclamation sweep added to the body-FK enumeration in both places (**corrects a pass-1 claim** that omitted it) — reclamation.py:43
- 3.6 — revise — ambiguity — donation obligation reads the carrier's effective utilization exactly as §3.4 defines it — workflows.py:194
- 3.6 — revise — mismatch — donation version bumps are conditional (donor carriers only if they donated, area code only if the run donated, rate center always) — workflows.py:203,213
- 3.7 — revise — ambiguity — sweep's `rate_center_id` must resolve (`ERR_RATE_CENTER_NOT_FOUND`); `reason_filter` accepts all four reasons — reclamation.py:40-44
- 3.7 — revise — mismatch — pass 3 filters `routing_status`, so it can also touch a block passes 1/2 just moved — workflows.py:85-158
- 3.7 — revise — mismatch — rate-center and area-code versions advanced by pass two alone — workflows.py:139-147
- 3.7 — revise — ambiguity — `VOLUNTARY_RETURN` is never issued by any endpoint; reachable only as a filter value — workflows.py:85
- 3.7 — insert — ambiguity — `appeal_note` optional 1–1000 chars, stored only by `APPEAL` — reclamation.py:84,110
- 3.7 — revise — mismatch — execution cascade version list; rate center and area code unconditional — reclamation.py:160-167
- 3.7 — revise — mismatch — withdrawal touches the rate center and never writes the area code — reclamation.py:177-188
- 3.8 — insert — ambiguity — port-creation precedence (FKs → ownership → `ERR_INVALID_REQUEST` pair → gaining-carrier eligibility); losing carrier's standing never examined — ports.py:64-84
- 3.8 — insert — ambiguity — supersession picks the most recently created match, keyed on TN and gaining carrier, leaving the earlier row at `SUBMITTED` — ports.py:102-111
- 3.8 — revise — mismatch — ownership test applies to every carrier-sent action; late `CONCUR` is `ERR_INVALID_STATE_TRANSITION`; `reject_reason` 1–500 — ports.py:157,161,176
- 3.8 — insert — ambiguity — activation record carries the superseded `switch_clli` and takes `ocn` from the block's holder — ports.py:210-219
- 3.8 — insert — ambiguity — snapback predecessor = row immediately before the open one regardless of `record_status`; fallback republishes the open record; no open record → nothing written, `npac_db_version` unmoved — ports.py:239-249
- 3.9 — insert — ambiguity — creation shape-checks `new_npa_code` without a uniqueness test and imposes no precondition on the code's `status` — relief.py:89-92
- 3.9 — insert — ambiguity — buffer check skipped with no `effective_at` and with a null newest `window_end_at`; ORDER excludes the plan itself — relief.py:54-70,281
- 3.9 — insert — mismatch — `OPEN_COMMENT` writes `RELIEF_PLANNED` directly, leaving `jeopardy_declared_at` and rate-center flags as they stood — relief.py:254-256
- 3.9 — revise — ambiguity — comment's plan comes from the path; body `relief_plan_id` shape-checked then ignored — relief.py:157
- 3.9 — insert — ambiguity — a comment against a `PLANNING` plan is also `ERR_COMMENT_WINDOW_CLOSED` — relief.py:167
- 3.9 — insert — ambiguity — first comment replaces both null weights, leaving each 0.00 for `OPPOSE_BOTH` — relief.py:180-183
- 3.9 — revise — mismatch — ORDER payload validated before the path plan resolves; successor freshly minted; `permissive_dialing_end_at` written onto the successor — relief.py:209-213,326-332
- 3.9 — insert — ambiguity — the relief-window buffer test runs ahead of the duplicate-code test, so a doubly-bad payload reports `ERR_RELIEF_WINDOW_OVERLAP` — relief.py:281-284
- 3.9 — revise — mismatch — overlay writes the parent straight to `ACTIVE` even with zero available blocks and, when it moved, clears the jeopardy stamp and flags — relief.py:338-341
- 3.9 — revise — ambiguity — split `moved_rate_center_ids` validation order, duplicates collapsed, blocks re-homed whatever their status; overlay ignores the list though its ids are still resolved — relief.py:310-353
- 3.9 — revise — mismatch — a partial split does not recompute the parent's `status`; retirement counted against pre-re-homing rate centers; retired blocks carry the successor's `npa_id` — relief.py:343-363
- 3.9 — revise — mismatch — `WITHDRAW` reversion bumps the code's `version` whether or not the posture changed, and is entered as though from `ACTIVE` — relief.py:298-301

### Closing integrity check (pass 3, re-verified by orchestrator)
- 494 lines; §4 holds all 50 endpoint rows; §5 holds all 43 `ERR_*` rows; 4 code-fence markers (balanced); file ends at a real boundary — last line is the completed §5 row `| ERR_GRANT_EXCEEDS_ENTITLEMENT | 422 |`; section headers intact §1→§5.
- No file under `implementation/`, `test_suite/` or `test_helpers/` was modified by any Step 9 pass (orchestrator confirmed via mtime scan against the 11:51 clean-sweep timestamp), so the 8/8 × 137-passing result from Step 7 still stands.

PIPELINE COMPLETE.
