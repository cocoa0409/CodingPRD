const db = require('../db/database');

function serializeTreatmentPlan(plan) {
  const serialized = {
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

  // Add policies if present
  if (plan.policies) {
    try {
      serialized.policies = typeof plan.policies === 'string' ? JSON.parse(plan.policies) : plan.policies;
    } catch (e) {
      serialized.policies = {};
    }
  }

  return serialized;
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
  const serialized = {
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

  // Add secondary_resource_requirements if present
  if (procedure.secondary_resource_requirements) {
    try {
      serialized.secondary_resource_requirements = typeof procedure.secondary_resource_requirements === 'string' 
        ? JSON.parse(procedure.secondary_resource_requirements) 
        : procedure.secondary_resource_requirements;
    } catch (e) {
      serialized.secondary_resource_requirements = [];
    }
  }

  return serialized;
}

function serializeMedicalResource(resource) {
  const certifications = db.prepare('SELECT id, name, applied_date FROM resource_certifications WHERE resource_id = ?')
    .all(resource.id);

  const serialized = {
    id: resource.id,
    plan_id: resource.plan_id,
    resource_name: resource.resource_name,
    resource_model: resource.resource_model,
    operating_cost_per_minute: resource.operating_cost_per_minute,
    status: resource.status,
    resource_certifications: certifications,
    created_at: resource.created_at,
    updated_at: resource.updated_at,
    version: resource.version
  };

  // Add maintenance_threshold_override if present
  if (resource.maintenance_threshold_override !== null && resource.maintenance_threshold_override !== undefined) {
    serialized.maintenance_threshold_override = resource.maintenance_threshold_override;
  }

  // Add sterilization_buffer_override if present
  if (resource.sterilization_buffer_override !== null && resource.sterilization_buffer_override !== undefined) {
    serialized.sterilization_buffer_override = resource.sterilization_buffer_override;
  }

  // Add overhead fields (defaults to 0)
  serialized.setup_overhead_minutes = resource.setup_overhead_minutes || 0;
  serialized.teardown_overhead_minutes = resource.teardown_overhead_minutes || 0;

  return serialized;
}

function serializeAssignment(assignment) {
  const serialized = {
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

  // Add secondary_resource_ids if present
  if (assignment.secondary_resource_ids) {
    try {
      serialized.secondary_resource_ids = typeof assignment.secondary_resource_ids === 'string' 
        ? JSON.parse(assignment.secondary_resource_ids) 
        : assignment.secondary_resource_ids;
    } catch (e) {
      serialized.secondary_resource_ids = [];
    }
  }

  // Expose count of resources that triggered biorisk (for debugging/observability)
  if (assignment.biorisk_crossing_resource_ids) {
    try {
      const ids = typeof assignment.biorisk_crossing_resource_ids === 'string'
        ? JSON.parse(assignment.biorisk_crossing_resource_ids)
        : assignment.biorisk_crossing_resource_ids;
      if (Array.isArray(ids)) serialized.high_biorisk_resource_count = ids.length;
    } catch (e) {
      // ignore parse errors
    }
  }

  // Expose per-resource biorisk debug if present
  if (assignment.biorisk_debug) {
    try {
      serialized.biorisk_debug = typeof assignment.biorisk_debug === 'string'
        ? JSON.parse(assignment.biorisk_debug)
        : assignment.biorisk_debug;
    } catch (e) {
      // ignore parse errors
    }
  }

  return serialized;
}

function serializeInfectionRiskPairing(pairing) {
  const serialized = {
    id: pairing.id,
    plan_id: pairing.plan_id,
    resource_id_1: pairing.resource_id_1,
    resource_id_2: pairing.resource_id_2,
    reason: pairing.reason,
    created_at: pairing.created_at
  };

  // Add quarantine_until_minute if present
  if (pairing.quarantine_until_minute !== null && pairing.quarantine_until_minute !== undefined) {
    serialized.quarantine_until_minute = pairing.quarantine_until_minute;
  }

  return serialized;
}

function serializeMaintenanceEvent(event) {
  return {
    id: event.id,
    plan_id: event.plan_id,
    resource_id: event.resource_id,
    at_minute: event.at_minute,
    created_at: event.created_at,
    version: event.version
  };
}

function serializeResourceHold(hold) {
  return {
    id: hold.id,
    plan_id: hold.plan_id,
    resource_id: hold.resource_id,
    start_minute: hold.start_minute,
    end_minute: hold.end_minute,
    reason: hold.reason,
    status: hold.status,
    created_at: hold.created_at,
    updated_at: hold.updated_at,
    version: hold.version
  };
}

function serializeOverrideAuthorization(auth) {
  return {
    id: auth.id,
    plan_id: auth.plan_id,
    assignment_id: auth.assignment_id,
    authorized_by_user_id: auth.authorized_by_user_id,
    created_at: auth.created_at
  };
}

module.exports = {
  serializeTreatmentPlan,
  serializeWardRotation,
  serializeProcedure,
  serializeMedicalResource,
  serializeAssignment,
  serializeInfectionRiskPairing,
  serializeMaintenanceEvent,
  serializeResourceHold,
  serializeOverrideAuthorization
};
