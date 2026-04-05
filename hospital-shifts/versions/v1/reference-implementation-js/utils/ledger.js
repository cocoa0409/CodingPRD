const db = require('../db/database');
const { getTimestamp } = require('./response');
const { roundToTwoDecimals } = require('./calculations');

function updateBudgetLedger(planId, incrementVersion = true) {
  const ledger = db.prepare('SELECT provisional_debits, finalized_debits FROM budget_ledgers WHERE plan_id = ?').get(planId);
  const plan = db.prepare('SELECT total_budget FROM treatment_plans WHERE id = ?').get(planId);

  if (ledger && plan) {
    const costBalance = roundToTwoDecimals(plan.total_budget - ledger.provisional_debits - ledger.finalized_debits);
    if (incrementVersion) {
      db.prepare('UPDATE treatment_plans SET cost_balance = ?, updated_at = ?, version = version + 1 WHERE id = ?')
        .run(costBalance, getTimestamp(), planId);
    } else {
      db.prepare('UPDATE treatment_plans SET cost_balance = ?, updated_at = ? WHERE id = ?')
        .run(costBalance, getTimestamp(), planId);
    }
  }
}

function updateSafetyLedger(planId, incrementVersion = true) {
  const ledger = db.prepare('SELECT safety_score FROM safety_ledgers WHERE plan_id = ?').get(planId);

  if (ledger) {
    if (incrementVersion) {
      db.prepare('UPDATE treatment_plans SET patient_safety_score = ?, updated_at = ?, version = version + 1 WHERE id = ?')
        .run(ledger.safety_score, getTimestamp(), planId);
    } else {
      db.prepare('UPDATE treatment_plans SET patient_safety_score = ?, updated_at = ? WHERE id = ?')
        .run(ledger.safety_score, getTimestamp(), planId);
    }
  }
}

// Mutators for ledgers only (no direct plan.version updates here)
function incrementBudgetLedger(planId, field, amount) {
  db.prepare(`UPDATE budget_ledgers SET ${field} = ${field} + ? WHERE plan_id = ?`).run(amount, planId);
}

function decrementBudgetLedger(planId, field, amount) {
  db.prepare(`UPDATE budget_ledgers SET ${field} = CASE WHEN ${field} - ? < 0 THEN 0 ELSE ${field} - ? END WHERE plan_id = ?`)
    .run(amount, amount, planId);
}

function incrementSafetyLedger(planId, amount) {
  db.prepare('UPDATE safety_ledgers SET safety_score = safety_score + ? WHERE plan_id = ?').run(amount, planId);
}

function decrementSafetyLedger(planId, amount) {
  db.prepare('UPDATE safety_ledgers SET safety_score = CASE WHEN safety_score - ? < 0 THEN 0 ELSE safety_score - ? END WHERE plan_id = ?')
    .run(amount, amount, planId);
}

// Sync both derived fields back to TreatmentPlan with a single optional version bump
function syncPlanDerivedFields(planId, incrementVersion = true) {
  const ledger = db.prepare('SELECT provisional_debits, finalized_debits FROM budget_ledgers WHERE plan_id = ?').get(planId);
  const safety = db.prepare('SELECT safety_score FROM safety_ledgers WHERE plan_id = ?').get(planId);
  const plan = db.prepare('SELECT total_budget FROM treatment_plans WHERE id = ?').get(planId);
  if (!ledger || !safety || !plan) return;
  const costBalance = roundToTwoDecimals(plan.total_budget - ledger.provisional_debits - ledger.finalized_debits);
  if (incrementVersion) {
    db.prepare('UPDATE treatment_plans SET cost_balance = ?, patient_safety_score = ?, updated_at = ?, version = version + 1 WHERE id = ?')
      .run(costBalance, safety.safety_score, getTimestamp(), planId);
  } else {
    db.prepare('UPDATE treatment_plans SET cost_balance = ?, patient_safety_score = ?, updated_at = ? WHERE id = ?')
      .run(costBalance, safety.safety_score, getTimestamp(), planId);
  }
}

module.exports = {
  updateBudgetLedger,
  updateSafetyLedger,
  incrementBudgetLedger,
  decrementBudgetLedger,
  incrementSafetyLedger,
  decrementSafetyLedger,
  syncPlanDerivedFields
};
