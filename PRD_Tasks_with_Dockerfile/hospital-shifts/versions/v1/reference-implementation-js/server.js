const express = require('express');
const { authenticate } = require('./middleware/auth');
const db = require('./db/database');

const app = express();
app.use(express.json());

app.use(authenticate);

app.use('/treatment-plans', require('./routes/treatmentPlans'));
app.use('/treatment-plans/:planId/ward-rotations', require('./routes/wardRotations'));
app.use('/treatment-plans/:planId/ward-rotations/:rotationId/procedures', require('./routes/procedures'));
app.use('/treatment-plans/:planId/medical-resources', require('./routes/medicalResources'));
app.use('/treatment-plans/:planId/assignments', require('./routes/assignments'));
app.use('/treatment-plans/:planId/infection-risk-pairings', require('./routes/infectionRiskPairings'));
app.use('/treatment-plans/:planId/finalize-plan', require('./routes/finalizePlan'));

app.use((req, res) => {
  const { createErrorResponse } = require('./utils/response');
  const error = createErrorResponse('ERR_INVALID_REQUEST', 'Endpoint not found', 404);
  res.status(error.statusCode).json(error.body);
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`Hospital Shift Scheduling API running on port ${PORT}`);
});
