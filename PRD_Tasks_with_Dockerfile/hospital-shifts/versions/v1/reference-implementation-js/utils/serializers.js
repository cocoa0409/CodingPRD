const db = require('../db/database');

function serializeTreatmentPlan(plan) {
  return {
    id: plan.id,
    plan_name: plan.plan_name,
    status: plan.status,
    total_budget: plan.total_budget,
    cost_balance: plan.cost_balance,
    patient_safety_score: plan.patient_safety_score,
    created_at: plan.created_at,
    updated_at: plan.updated_at,
    version: plan.version
  };
}

function serializeWardRotation(rotation) {
  return {
    id: rotation.id,
    plan_id: rotation.plan_id,
    name: rotation.name,
    status: rotation.status,
    start_minute: rotation.start_minute,
    end_minute: rotation.end_minute,
    created_at: rotation.created_at,
    updated_at: rotation.updated_at,
    version: rotation.version
  };
}

function serializeProcedure(procedure) {
  return {
    id: procedure.id,
    rotation_id: procedure.rotation_id,
    plan_id: procedure.plan_id,
    procedure_type: procedure.procedure_type,
    status: procedure.status,
    required_certification: procedure.required_certification,
    start_minute: procedure.start_minute,
    end_minute: procedure.end_minute,
    duration_minutes: procedure.duration_minutes,
    created_at: procedure.created_at,
    updated_at: procedure.updated_at,
    version: procedure.version
  };
}

function serializeMedicalResource(resource) {
  const certifications = db.prepare('SELECT id, name, applied_date FROM resource_certifications WHERE resource_id = ?')
    .all(resource.id);

  return {
    id: resource.id,
    plan_id: resource.plan_id,
    resource_name: resource.resource_name,
    resource_model: resource.resource_model,
    operating_cost_per_minute: resource.operating_cost_per_minute,
    resource_certifications: certifications,
    created_at: resource.created_at,
    updated_at: resource.updated_at,
    version: resource.version
  };
}

function serializeAssignment(assignment) {
  return {
    id: assignment.id,
    plan_id: assignment.plan_id,
    procedure_id: assignment.procedure_id,
    resource_id: assignment.resource_id,
    status: assignment.status,
    override_protocol_check: Boolean(assignment.override_protocol_check),
    protocol_override_penalty_applied: Boolean(assignment.protocol_override_penalty_applied),
    is_high_biorisk: Boolean(assignment.is_high_biorisk),
    provisional_cost: assignment.provisional_cost,
    final_cost: assignment.final_cost,
    created_at: assignment.created_at,
    updated_at: assignment.updated_at,
    version: assignment.version
  };
}

function serializeInfectionRiskPairing(pairing) {
  return {
    id: pairing.id,
    plan_id: pairing.plan_id,
    resource_id_1: pairing.resource_id_1,
    resource_id_2: pairing.resource_id_2,
    reason: pairing.reason,
    created_at: pairing.created_at
  };
}

module.exports = {
  serializeTreatmentPlan,
  serializeWardRotation,
  serializeProcedure,
  serializeMedicalResource,
  serializeAssignment,
  serializeInfectionRiskPairing
};
