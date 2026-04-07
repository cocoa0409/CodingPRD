import express, { Request, Response, NextFunction } from 'express';
import { initializeDatabase } from './db/schema';
import studiosRouter from './routes/studios';
import assetsRouter from './routes/assets';
import clearancesRouter from './routes/clearances';
import mixesRouter from './routes/mixes';
import disputesRouter from './routes/disputes';
import { ERROR_CODES } from './types';

const app = express();
const PORT = process.env.PORT || 3000;

initializeDatabase();

app.use(express.json());

app.use((req: Request, res: Response, next: NextFunction) => {
  if (req.method !== 'GET' && req.method !== 'DELETE') {
    const contentType = req.headers['content-type'];
    if (!contentType || !contentType.includes('application/json')) {
      res.status(400).json({
        error: { code: ERROR_CODES.BAD_REQUEST, message: 'Content-Type must be application/json' }
      });
      return;
    }
  }
  next();
});

app.use('/studios', studiosRouter);
app.use('/studios', assetsRouter);
app.use('/studios', clearancesRouter);
app.use('/studios', mixesRouter);
app.use('/studios', disputesRouter);

app.get('/health', (req: Request, res: Response) => {
  res.json({ status: 'ok' });
});

app.use((req: Request, res: Response) => {
  res.status(404).json({
    error: { code: ERROR_CODES.NOT_FOUND, message: 'Endpoint not found' }
  });
});

app.use((err: Error, req: Request, res: Response, next: NextFunction) => {
  console.error('Unhandled error:', err);
  res.status(500).json({
    error: { code: ERROR_CODES.BAD_REQUEST, message: 'Internal server error' }
  });
});

app.listen(PORT, () => {
  console.log(`PulseMix Studio API running on port ${PORT}`);
});

export default app;
